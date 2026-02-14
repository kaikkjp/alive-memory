-- migrations/011_multi_visitor.sql
-- Multi-slot visitor presence: multiple visitors in the shop simultaneously.
-- Replaces the singleton engagement model with a per-visitor presence table.

CREATE TABLE IF NOT EXISTS visitors_present (
    visitor_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'browsing',   -- browsing | in_conversation | waiting | left
    entered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    connection_type TEXT NOT NULL DEFAULT 'tcp'  -- tcp | websocket
);

CREATE INDEX IF NOT EXISTS idx_vp_status ON visitors_present(status);
