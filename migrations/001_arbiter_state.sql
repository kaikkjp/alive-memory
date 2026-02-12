-- Migration 001: Arbiter state table for Living Loop cycle planning
-- Tracks per-day caps, per-channel cooldowns, and novelty penalty keywords.

CREATE TABLE IF NOT EXISTS arbiter_state (
    singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
    consume_count_today INTEGER NOT NULL DEFAULT 0,
    news_engage_count_today INTEGER NOT NULL DEFAULT 0,
    thread_focus_count_today INTEGER NOT NULL DEFAULT 0,
    express_count_today INTEGER NOT NULL DEFAULT 0,
    last_consume_ts TIMESTAMP,
    last_news_engage_ts TIMESTAMP,
    last_thread_focus_ts TIMESTAMP,
    last_express_ts TIMESTAMP,
    recent_focus_keywords JSON NOT NULL DEFAULT '[]',
    current_date_jst TEXT NOT NULL DEFAULT ''
);

INSERT OR IGNORE INTO arbiter_state (singleton_key, current_date_jst)
VALUES (1, date('now', '+9 hours'));
