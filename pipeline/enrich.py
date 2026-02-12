"""URL Enrichment — fetch metadata when a visitor shares a URL."""

import asyncio
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
import urllib.error


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


async def fetch_readable_text(url: str, max_chars: int = 4000) -> str:
    """Fetch readable text content from a URL for consumption.

    Reads up to 32KB of HTML and extracts a text approximation.
    Returns truncated plain text suitable for Cortex prompt.
    """
    return await asyncio.to_thread(_fetch_readable_text_sync, url, max_chars)


def _fetch_readable_text_sync(url: str, max_chars: int = 4000) -> str:
    """Sync implementation — fetch and extract readable text."""
    try:
        if not _validate_url(url):
            return ''

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
