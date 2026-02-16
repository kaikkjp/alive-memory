"""Tests for feed enrichment via markdown.new (TASK-034).

Tests:
- Article enrichment via markdown.new
- Video transcript detection
- Music metadata detection
- Fallback behavior when markdown.new unavailable
- Content type detection heuristics
- No duplicate enrichment (rate limiting per URL)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import db
from pipeline.enrich import (
    fetch_via_markdown_new,
    fetch_readable_text,
    detect_content_type,
    _fetch_via_markdown_new_sync,
    _fetch_readable_text_sync,
)
from feed_ingester import enrich_pool_item


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp database for each test."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


# ── Content type detection tests ──

class TestContentTypeDetection:
    """detect_content_type() correctly classifies enriched markdown."""

    def test_empty_text_is_article(self):
        assert detect_content_type('') == 'article'

    def test_none_text_is_article(self):
        assert detect_content_type(None) == 'article'

    def test_prose_is_article(self):
        text = """# The Art of Kintsugi

        Kintsugi is the Japanese art of repairing broken pottery with gold.
        The philosophy behind it treats breakage as part of the object's history,
        rather than something to disguise. Each repaired piece is unique, and
        the golden seams make the object more beautiful than before."""
        assert detect_content_type(text) == 'article'

    def test_video_transcript_detected(self):
        text = """# Walking Through Shimokitazawa at Night

        Channel: TokyoWalks  Views: 1.2M
        Duration: 45:23

        ## Transcript

        0:00 Starting at the south exit of Shimokitazawa station
        0:15 The narrow streets are lined with vintage shops
        2:30 A small jazz bar with live music filtering through the door
        """
        assert detect_content_type(text) == 'video'

    def test_youtube_url_with_transcript(self):
        text = """# Ambient Rain Sounds in Tokyo

        Source: youtube.com/watch?v=abc123

        Transcript:
        The sound of rain on temple rooftops in Kamakura.
        """
        assert detect_content_type(text) == 'video'

    def test_music_metadata_detected(self):
        text = """# Hiroshi Yoshimura — Music for Nine Post Cards

        Artist: Hiroshi Yoshimura
        Album: Music for Nine Post Cards
        Label: Sound Process
        Genre: Ambient, Environmental

        Tracklist:
        1. Water Copy
        2. Clouds
        3. Feel
        """
        assert detect_content_type(text) == 'music'

    def test_bandcamp_page_detected_as_music(self):
        text = """# New Release on Bandcamp

        Found on bandcamp.com/tag/ambient
        Artist: Midori Takada
        Album: Through the Looking Glass
        Release: 1983, reissued 2017
        """
        assert detect_content_type(text) == 'music'

    def test_article_with_single_video_mention_stays_article(self):
        """One video signal alone shouldn't trigger video classification."""
        text = """# The History of Tokyo Tower

        Tokyo Tower was completed in 1958. It was inspired by the Eiffel Tower.
        You can watch a video about its construction on youtube.com.
        The observation deck offers stunning views of the city.
        """
        assert detect_content_type(text) == 'article'

    def test_article_with_single_music_mention_stays_article(self):
        """One music signal alone shouldn't trigger music classification."""
        text = """# A Guide to Daikanyama Cafes

        Many cafes in Daikanyama play ambient music. The genre is popular
        here among the creative crowd who frequent the neighborhood.
        """
        assert detect_content_type(text) == 'article'


# ── markdown.new fetch tests ──

class TestFetchViaMarkdownNew:
    """fetch_via_markdown_new() calls the API and returns markdown."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        """markdown.new returns clean markdown for a valid URL."""
        mock_markdown = "# Test Article\n\nThis is clean markdown content."
        with patch('pipeline.enrich._validate_url', return_value=True), \
             patch('pipeline.enrich._fetch_via_markdown_new_sync', return_value=mock_markdown):
            result = await fetch_via_markdown_new('https://example.com/article')
        assert result == mock_markdown

    @pytest.mark.asyncio
    async def test_invalid_url_returns_empty(self):
        """Invalid URLs are rejected before hitting the API."""
        with patch('pipeline.enrich._validate_url', return_value=False):
            result = await fetch_via_markdown_new('ftp://invalid.local')
        assert result == ''

    @pytest.mark.asyncio
    async def test_api_failure_returns_empty(self):
        """Service unavailable returns empty string."""
        with patch('pipeline.enrich._validate_url', return_value=True), \
             patch('pipeline.enrich._fetch_via_markdown_new_sync', return_value=''):
            result = await fetch_via_markdown_new('https://example.com/article')
        assert result == ''


# ── fetch_readable_text fallback tests ──

class TestFetchReadableTextFallback:
    """fetch_readable_text() tries markdown.new first, falls back to HTML extraction."""

    @pytest.mark.asyncio
    async def test_uses_markdown_new_when_available(self):
        """When markdown.new succeeds, its output is returned."""
        mock_md = "# Clean Article\n\nParagraph text."
        with patch('pipeline.enrich._validate_url', return_value=True), \
             patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=mock_md):
            result = await fetch_readable_text('https://example.com/article')
        assert result == mock_md

    @pytest.mark.asyncio
    async def test_falls_back_on_markdown_new_failure(self):
        """When markdown.new fails, falls back to HTML extraction."""
        fallback_text = "Extracted HTML text content"
        with patch('pipeline.enrich._validate_url', return_value=True), \
             patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=''), \
             patch('pipeline.enrich._fetch_readable_text_sync', return_value=fallback_text):
            result = await fetch_readable_text('https://example.com/article')
        assert result == fallback_text

    @pytest.mark.asyncio
    async def test_respects_max_chars(self):
        """Output is truncated to max_chars."""
        long_md = "# Title\n\n" + "x" * 10000
        with patch('pipeline.enrich._validate_url', return_value=True), \
             patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=long_md):
            result = await fetch_readable_text('https://example.com/article', max_chars=100)
        assert len(result) == 100

    @pytest.mark.asyncio
    async def test_invalid_url_returns_empty(self):
        """Invalid URLs return empty without hitting any service."""
        with patch('pipeline.enrich._validate_url', return_value=False):
            result = await fetch_readable_text('ftp://bad.local')
        assert result == ''


# ── Enrichment dedup / rate limiting tests ──

class TestEnrichmentDedup:
    """enrich_pool_item() doesn't hit markdown.new twice for the same URL."""

    @pytest.mark.asyncio
    async def test_first_enrichment_succeeds(self):
        """First enrichment of a URL calls markdown.new and stores result."""
        url = 'https://example.com/test-article'
        # Add a pool item
        await db.add_to_content_pool(
            fingerprint='fp_test_001',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Test Article',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']

        mock_md = "# Test Article\n\nClean prose about Tokyo."
        with patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=mock_md), \
             patch('pipeline.enrich.detect_content_type', return_value='article'):
            result = await enrich_pool_item(pool_id, url)

        assert result == 'article'
        # Verify stored in DB
        item = await db.get_pool_item_by_id(pool_id)
        assert item['enriched_text'] == mock_md
        assert item['content_type'] == 'article'

    @pytest.mark.asyncio
    async def test_duplicate_enrichment_skipped(self):
        """Second enrichment of same URL is skipped (rate limiting)."""
        url = 'https://example.com/test-article-dup'
        # Add a pool item with enriched_text already set
        await db.add_to_content_pool(
            fingerprint='fp_test_002',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Test Article',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']

        # First enrichment
        await db.update_pool_item(pool_id, enriched_text='already enriched', content_type='article')

        # Try to enrich again — should be skipped
        with patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock) as mock_fetch:
            result = await enrich_pool_item(pool_id, url)

        assert result is None
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_markdown_new_failure_returns_none(self):
        """When markdown.new fails, enrich_pool_item returns None."""
        url = 'https://example.com/failing-article'
        await db.add_to_content_pool(
            fingerprint='fp_test_003',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Failing Article',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']

        with patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=''):
            result = await enrich_pool_item(pool_id, url)

        assert result is None


# ── Video transcript enrichment test ──

class TestVideoEnrichment:
    """YouTube/video URLs are enriched and tagged correctly."""

    @pytest.mark.asyncio
    async def test_youtube_url_tagged_as_video(self):
        """A YouTube URL returning a transcript gets content_type='video'."""
        url = 'https://www.youtube.com/watch?v=abc123'
        await db.add_to_content_pool(
            fingerprint='fp_video_001',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Tokyo Night Walk',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']

        video_md = """# Tokyo Night Walk

        Channel: TokyoWalks  Views: 500K
        Duration: 32:10

        ## Transcript

        0:00 Starting near Shibuya crossing
        1:30 The neon lights reflect off wet pavement
        """
        with patch('pipeline.enrich.fetch_via_markdown_new', new_callable=AsyncMock, return_value=video_md):
            result = await enrich_pool_item(pool_id, url)

        assert result == 'video'
        item = await db.get_pool_item_by_id(pool_id)
        assert item['content_type'] == 'video'


# ── DB enrichment column tests ──

class TestDBEnrichmentColumns:
    """Database correctly stores and retrieves enriched_text and content_type."""

    @pytest.mark.asyncio
    async def test_get_enriched_text_for_url_found(self):
        """Returns enriched_text when URL has been enriched."""
        url = 'https://example.com/enriched-url'
        await db.add_to_content_pool(
            fingerprint='fp_db_001',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Enriched',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']
        await db.update_pool_item(pool_id, enriched_text='# Enriched content')

        result = await db.get_enriched_text_for_url(url)
        assert result == '# Enriched content'

    @pytest.mark.asyncio
    async def test_get_enriched_text_for_url_not_found(self):
        """Returns None when URL has not been enriched."""
        result = await db.get_enriched_text_for_url('https://example.com/not-enriched')
        assert result is None

    @pytest.mark.asyncio
    async def test_update_pool_item_content_type(self):
        """content_type column is correctly stored and retrieved."""
        url = 'https://example.com/typed-url'
        await db.add_to_content_pool(
            fingerprint='fp_db_002',
            source_type='url',
            source_channel='rss',
            content=url,
            title='Typed',
        )
        items = await db.get_pool_items(status='unseen')
        pool_id = items[0]['id']
        await db.update_pool_item(pool_id, content_type='music')

        item = await db.get_pool_item_by_id(pool_id)
        assert item['content_type'] == 'music'
