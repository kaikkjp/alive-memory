"""Feed source configuration."""

# Sources the feed ingester will poll
FEED_SOURCES = [
    # Static URL/quote lists (one item per line)
    {'type': 'file', 'path': 'demo/content/readings.txt', 'tags': ['curated']},

    # Core — her identity
    {'type': 'rss', 'url': 'https://www.spoon-tamago.com/feed/', 'tags': ['tokyo', 'design', 'craft', 'japan']},
    {'type': 'rss', 'url': 'https://aeon.co/feed.rss', 'tags': ['philosophy', 'essays', 'ideas']},
    {'type': 'rss', 'url': 'https://www.themarginalian.org/feed/', 'tags': ['philosophy', 'literature', 'wisdom']},
    {'type': 'rss', 'url': 'https://publicdomainreview.org/feed/', 'tags': ['history', 'curiosities', 'visual_archive']},
    {'type': 'rss', 'url': 'https://www.tokyoartbeat.com/en/feed', 'tags': ['tokyo', 'art', 'exhibitions']},

    # Adjacent — serendipity
    {'type': 'rss', 'url': 'https://www.ambientblog.net/blog/feed', 'tags': ['ambient', 'music', 'soundscapes']},
    {'type': 'rss', 'url': 'https://www.messynessychic.com/feed/', 'tags': ['exploration', 'nostalgia', 'hidden_places']},
    {'type': 'rss', 'url': 'https://www.lensculture.com/rss', 'tags': ['photography', 'visual', 'artists']},

    # Multimedia — enriched via markdown.new (TASK-034)
    {'type': 'rss', 'url': 'https://www.youtube.com/feeds/videos.xml?channel_id=UCshv6RacCMEMl3SncgMkmqQ', 'tags': ['video', 'tokyo', 'walks']},  # Rambalac — Tokyo walks
    {'type': 'rss', 'url': 'https://daily.bandcamp.com/feed', 'tags': ['music', 'discovery', 'independent']},  # Bandcamp Daily
]

FEED_FETCH_INTERVAL = 3600   # seconds between feed checks (1 hour)
MAX_POOL_UNSEEN = 200        # cap unseen items; oldest non-curated expire when exceeded
