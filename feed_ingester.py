"""Feed Ingester — fetches content from RSS/file sources into the content pool.

Runs as a periodic task inside heartbeat or as a standalone import.
Idempotent: duplicate content is ignored via fingerprint uniqueness.
Enriches URL items via markdown.new when available (TASK-034).
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import db

logger = logging.getLogger(__name__)


def compute_pool_fingerprint(source_channel: str, source_type: str, content: str) -> str:
    """Compute a deterministic fingerprint for deduplication.

    Canonicalizes: strip UTM params from URLs, lowercase, collapse whitespace.
    """
    canonical = canonicalize_content(source_type, content)
    raw = f"{source_channel}|{source_type}|{canonical}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def canonicalize_content(source_type: str, content: str) -> str:
    """Normalize content for fingerprinting."""
    if source_type == 'url':
        # Strip UTM and tracking params
        content = re.sub(r'[?&](utm_\w+|ref|source|fbclid|gclid)=[^&]*', '', content)
        # Remove trailing ? or & left over
        content = content.rstrip('?&')
    # Lowercase, collapse whitespace
    content = content.lower().strip()
    content = re.sub(r'\s+', ' ', content)
    return content


async def enrich_pool_item(pool_id: str, url: str) -> Optional[str]:
    """Enrich a content pool item via markdown.new. Rate-limited per URL.

    Checks if this URL was already enriched (dedup). If not, fetches via
    markdown.new, detects content type, and stores enriched_text + content_type.

    Returns content_type on success, None if already enriched or on failure.
    """
    from pipeline.enrich import fetch_via_markdown_new, detect_content_type

    # Rate limiting: don't hit markdown.new more than once per URL
    existing = await db.get_enriched_text_for_url(url)
    if existing is not None:
        logger.debug("[FeedIngester] URL already enriched, skipping: %s", url[:80])
        return None

    markdown_text = await fetch_via_markdown_new(url)
    if not markdown_text:
        return None

    content_type = detect_content_type(markdown_text)
    await db.update_pool_item(
        pool_id,
        enriched_text=markdown_text,
        content_type=content_type,
    )
    logger.debug("[FeedIngester] Enriched %s as %s (%d chars)", url[:60], content_type, len(markdown_text))
    return content_type


async def ingest_from_file(filepath: str, tags: list[str] = None) -> int:
    """Ingest URLs/quotes from a text file (one per line).

    Returns number of new items added (skips duplicates).
    """
    import pathlib
    path = pathlib.Path(filepath)
    if not path.exists():
        logger.warning("Feed file not found: %s", filepath)
        return 0

    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith('#')]
    added = 0

    for line in lines:
        is_url = bool(re.match(r'https?://', line))
        source_type = 'url' if is_url else 'text'

        # Cross-channel dedup: skip if this URL already exists from any channel
        if is_url and await db.url_exists_in_pool(line):
            continue

        fingerprint = compute_pool_fingerprint('file', source_type, line)

        title = line[:80] if not is_url else ''
        if is_url:
            # Try to extract a clean title from the URL path
            parts = line.rstrip('/').rsplit('/', 1)
            title = parts[-1].replace('-', ' ').replace('_', ' ')[:80] if len(parts) > 1 else line[:80]

        result = await db.add_to_content_pool(
            fingerprint=fingerprint,
            source_type=source_type,
            source_channel='file',
            content=line,
            title=title,
            metadata={},
            tags=tags or [],
            ttl_hours=None,  # curated content doesn't expire
        )
        if result:
            added += 1

    return added


async def ingest_from_rss(feed_url: str, tags: list[str] = None) -> int:
    """Ingest items from an RSS feed.

    Requires feedparser: pip install feedparser
    Returns number of new items added.
    """
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed. Run: pip install feedparser")
        return 0

    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", feed_url, e)
        return 0

    added = 0
    for entry in feed.entries[:20]:  # cap at 20 per fetch
        link = entry.get('link', '')
        title = entry.get('title', '')

        if not link and not title:
            continue

        content = link or title
        source_type = 'url' if link else 'rss_headline'

        # Cross-channel dedup: skip if this URL already exists from any channel
        if link and await db.url_exists_in_pool(link):
            continue

        fingerprint = compute_pool_fingerprint('rss', source_type, content)

        metadata = {}
        if entry.get('summary'):
            metadata['description'] = entry.summary[:300]
        if entry.get('author'):
            metadata['author'] = entry.author

        result = await db.add_to_content_pool(
            fingerprint=fingerprint,
            source_type=source_type,
            source_channel='rss',
            content=content,
            title=title[:200],
            metadata=metadata,
            tags=tags or [],
            ttl_hours=4.0,  # headlines expire in 4 hours
        )
        if result:
            added += 1

    return added


async def run_feed_ingestion() -> int:
    """Run one pass of all configured feed sources.

    After ingesting RSS items, enriches URL items via markdown.new.
    Returns total items added.
    """
    from config.feeds import FEED_SOURCES

    total = 0
    for source in FEED_SOURCES:
        try:
            if source['type'] == 'file':
                count = await ingest_from_file(source['path'], source.get('tags', []))
            elif source['type'] == 'rss':
                count = await ingest_from_rss(source['url'], source.get('tags', []))
            else:
                logger.warning("Unknown feed type: %s", source['type'])
                continue
            total += count
            if count > 0:
                logger.info("Ingested %d items from %s", count, source.get('url', source.get('path', '?')))
        except Exception as e:
            logger.warning("Feed source error: %s — %s", source, e)

    # Enrich newly added URL items via markdown.new
    await _enrich_unseen_urls()

    return total


async def _enrich_unseen_urls():
    """Enrich unseen URL pool items that haven't been enriched yet."""
    items = await db.get_pool_items(status='unseen', source_types=['url'], limit=20)
    enriched = 0
    for item in items:
        url = item.get('content', '')
        pool_id = item.get('id', '')
        if not url or not pool_id:
            continue
        # Skip if already enriched
        if item.get('enriched_text'):
            continue
        try:
            result = await enrich_pool_item(pool_id, url)
            if result:
                enriched += 1
        except Exception as e:
            logger.debug("[FeedIngester] Enrichment failed for %s: %s", url[:60], e)
    if enriched > 0:
        logger.info("[FeedIngester] Enriched %d URL items via markdown.new", enriched)


async def embed_unseen_titles():
    """Pre-embed titles of unseen content pool items for gap detection (TASK-042).

    Embeds titles using pipeline/embed.py and stores the embedding vector in
    content_pool.title_embedding. Gap detection at cycle time is then pure
    vector math — no API calls needed.
    """
    from pipeline.embed import embed, embed_session

    items = await db.get_pool_items(status='unseen', limit=30)
    embedded = 0

    async with embed_session():
        for item in items:
            title = item.get('title', '')
            pool_id = item.get('id', '')
            if not title or not pool_id:
                continue
            # Skip if already embedded
            if item.get('title_embedding'):
                continue
            try:
                vec = await embed(title)
                if vec:
                    import struct
                    blob = struct.pack(f'{len(vec)}f', *vec)
                    await db.update_pool_item(pool_id, title_embedding=blob)
                    embedded += 1
            except Exception as e:
                logger.debug("[FeedIngester] Title embedding failed for %s: %s",
                             title[:40], e)

    if embedded > 0:
        logger.info("[FeedIngester] Embedded %d titles for gap detection", embedded)
