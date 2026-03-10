-- Semantic memory: totems, visitor traits, visitor knowledge
-- Ports structured fact storage from Shopkeeper engine

-- Totems — weighted semantic associations (facts, entities, concepts)
-- Can be global (visitor_id IS NULL) or visitor-specific
CREATE TABLE IF NOT EXISTS totems (
    id TEXT PRIMARY KEY,
    visitor_id TEXT,
    entity TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    context TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    first_seen TEXT NOT NULL,
    last_referenced TEXT NOT NULL,
    source_moment_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_totems_visitor ON totems(visitor_id);
CREATE INDEX IF NOT EXISTS idx_totems_entity ON totems(entity);
CREATE INDEX IF NOT EXISTS idx_totems_weight ON totems(weight);

-- Visitor traits — structured observations about visitors
CREATE TABLE IF NOT EXISTS visitor_traits (
    id TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL,
    trait_category TEXT NOT NULL,
    trait_key TEXT NOT NULL,
    trait_value TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    source_moment_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traits_visitor ON visitor_traits(visitor_id);
CREATE INDEX IF NOT EXISTS idx_traits_category ON visitor_traits(trait_category);
CREATE INDEX IF NOT EXISTS idx_traits_key ON visitor_traits(visitor_id, trait_category, trait_key);

-- Visitors — knowledge about people the agent interacts with
CREATE TABLE IF NOT EXISTS visitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trust_level TEXT NOT NULL DEFAULT 'stranger',
    visit_count INTEGER NOT NULL DEFAULT 1,
    first_visit TEXT NOT NULL,
    last_visit TEXT NOT NULL,
    emotional_imprint TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_visitors_name ON visitors(name);
