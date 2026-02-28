"""URL Enrichment — fetch metadata when a visitor shares a URL.

Supports markdown.new for clean markdown conversion (TASK-034).
Falls back to raw HTML extraction when markdown.new is unavailable.
"""

import asyncio
import ipaddress
import json
import logging
import re
import socket
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# markdown.new endpoint
MARKDOWN_NEW_URL = 'https://markdown.new/'
MARKDOWN_NEW_TIMEOUT = 15  # seconds — external service, allow more time


def _validate_url(url: str) -> bool:
    """Validate URL is safe to fetch. Reject private IPs, non-standard ports, bad schemes."""
    try:
        parsed = urllib.parse.urlparse(url)

        # Must be http or https
        if parsed.scheme not in ('http', 'https'):
            return False

        # Reject non-standard ports (only 80/443 or default)
        if parsed.port is not None and parsed.port not in (80, 443):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname and check for private IP ranges
        try:
            addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return False  # can't resolve → reject

        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False

        return True
    except Exception:
        return False


async def fetch_url_metadata(url: str) -> dict:
    """Fetch title and description from a URL. Runs in thread to avoid blocking."""
    return await asyncio.to_thread(_fetch_url_metadata_sync, url)


def _fetch_url_metadata_sync(url: str) -> dict:
    """Sync implementation — called via to_thread."""
    try:
        # SSRF protection: validate URL before fetching
        if not _validate_url(url):
            return {
                'title': 'blocked',
                'description': 'URL validation failed',
                'site': '',
                'url': url,
            }

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Shopkeeper/1.0)',
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read(8192).decode('utf-8', errors='replace')

        title = ''
        desc = ''
        site = ''

        # Extract title
        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()[:200]

        # Extract meta description
        m = re.search(
            r'<meta\s+(?:name|property)=["\'](?:description|og:description)["\']\s+content=["\']([^"\']*)["\']',
            html, re.IGNORECASE
        )
        if not m:
            m = re.search(
                r'<meta\s+content=["\']([^"\']*)["\']\s+(?:name|property)=["\'](?:description|og:description)["\']',
                html, re.IGNORECASE
            )
        if m:
            desc = m.group(1).strip()[:300]

        # Extract site name
        m = re.search(
            r'<meta\s+(?:property)=["\']og:site_name["\']\s+content=["\']([^"\']*)["\']',
            html, re.IGNORECASE
        )
        if m:
            site = m.group(1).strip()
        else:
            # Fallback: domain name
            m = re.match(r'https?://(?:www\.)?([^/]+)', url)
            if m:
                site = m.group(1)

        return {
            'title': title or 'untitled',
            'description': desc,
            'site': site,
            'url': url,
        }

    except Exception:
        return {
            'title': 'unknown',
            'description': '',
            'site': '',
            'url': url,
        }


# ── markdown.new integration (TASK-034) ──

def _fetch_via_markdown_new_sync(url: str) -> str:
    """Fetch clean markdown for a URL via markdown.new. Sync implementation.

    Returns markdown string on success, empty string on failure.
    """
    try:
        api_url = MARKDOWN_NEW_URL
        payload = json.dumps({'url': url}).encode('utf-8')
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Shopkeeper/1.0',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=MARKDOWN_NEW_TIMEOUT) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        logger.debug("[Enrich] markdown.new failed for %s: %s", url, e)
        return ''


async def fetch_via_markdown_new(url: str) -> str:
    """Fetch clean markdown for a URL via markdown.new.

    Returns markdown string on success, empty string on failure.
    Thread-safe: runs sync HTTP in a thread.
    """
    if not _validate_url(url):
        return ''
    return await asyncio.to_thread(_fetch_via_markdown_new_sync, url)


def detect_content_type(markdown_text: str) -> str:
    """Detect content type from enriched markdown output.

    Returns one of: 'video', 'music', 'article'.

    Heuristics:
    - 'video' if text contains transcript markers or YouTube/video metadata
    - 'music' if text contains track/album metadata patterns
    - 'article' otherwise (default for prose)
    """
    if not markdown_text:
        return 'article'

    lower = markdown_text.lower()

    # Video detection: transcript markers, YouTube metadata, duration patterns
    video_signals = [
        'transcript' in lower,
        'captions' in lower and ('video' in lower or 'youtube' in lower),
        bool(re.search(r'duration[:\s]+\d+:\d+', lower)),
        bool(re.search(r'(youtube\.com|youtu\.be|vimeo\.com)', lower)),
        'channel:' in lower and 'views' in lower,
        bool(re.search(r'^\s*\d{1,2}:\d{2}', markdown_text, re.MULTILINE)),  # timestamp lines
    ]
    if sum(video_signals) >= 2:
        return 'video'

    # Music detection: track/album/artist metadata patterns
    music_signals = [
        bool(re.search(r'(track\s*list|tracklist)', lower)),
        bool(re.search(r'(bandcamp\.com|soundcloud\.com|spotify\.com)', lower)),
        bool(re.search(r'(album|release|ep)\s*:', lower)),
        bool(re.search(r'artist\s*:', lower)),
        'genre:' in lower,
        bool(re.search(r'bpm\s*:', lower)),
        bool(re.search(r'(label|record\s*label)\s*:', lower)),
    ]
    if sum(music_signals) >= 2:
        return 'music'

    return 'article'


async def fetch_readable_text(url: str, max_chars: int = 4000) -> str:
    """Fetch readable text content from a URL for consumption.

    Tries markdown.new first for clean markdown extraction.
    Falls back to raw HTML text extraction if markdown.new is unavailable.
    Returns truncated text suitable for Cortex prompt.
    """
    if not _validate_url(url):
        return ''

    # Try markdown.new first
    markdown_text = await fetch_via_markdown_new(url)
    if markdown_text:
        return markdown_text[:max_chars]

    # Fallback: raw HTML extraction
    return await asyncio.to_thread(_fetch_readable_text_sync, url, max_chars)


def _fetch_readable_text_sync(url: str, max_chars: int = 4000) -> str:
    """Sync fallback — fetch HTML and extract text."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Shopkeeper/1.0)',
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read(32768).decode('utf-8', errors='replace')

        # Strip HTML tags to get approximate text
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Decode HTML entities
        import html as html_module
        text = html_module.unescape(text)

        return text[:max_chars]
    except Exception:
        return ''
