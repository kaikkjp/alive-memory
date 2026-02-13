"""Feed source configuration."""

# Sources the feed ingester will poll
FEED_SOURCES = [
    # Static URL/quote lists (one item per line)
    # {'type': 'file', 'path': 'content/readings.txt', 'tags': ['curated']},

    # RSS feeds
    # {'type': 'rss', 'url': 'https://www.tokyoartbeat.com/en/feed', 'tags': ['art', 'tokyo']},
]

FEED_FETCH_INTERVAL = 3600   # seconds between feed checks (1 hour)
MAX_POOL_UNSEEN = 50         # cap unseen items; oldest expire when exceeded
