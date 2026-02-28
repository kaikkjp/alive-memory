"""Feed source configuration.

Agents start with an empty feed. Managers add streams via the lounge UI
or the /api/agents/:id/feed/streams endpoint.
"""

# Sources the feed ingester will poll — empty by default.
# Managers configure per-agent feeds through the lounge.
FEED_SOURCES: list[dict] = []

FEED_FETCH_INTERVAL = 3600   # seconds between feed checks (1 hour)
MAX_POOL_UNSEEN = 200        # cap unseen items; oldest non-curated expire when exceeded
