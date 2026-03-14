"""Preset config profiles for autotune."""

from __future__ import annotations

PROFILES: dict[str, dict] = {
    "default": {},

    "high_recall": {
        "intake.base_salience": 0.35,
        "intake.salience_threshold": 0.25,
        "intake.max_day_moments": 60,
        "recall.default_limit": 20,
        "recall.context_lines": 5,
        "consolidation.cold_embed_limit": 100,
    },

    "low_noise": {
        "intake.base_salience": 0.6,
        "intake.salience_threshold": 0.5,
        "intake.max_day_moments": 15,
        "intake.dedup_similarity": 0.7,
        "recall.default_limit": 5,
    },

    "fast_consolidation": {
        "consolidation.dream_count": 1,
        "consolidation.reflection_count": 1,
        "consolidation.nap_moment_count": 3,
        "consolidation.cold_embed_limit": 20,
    },

    "deep_identity": {
        "identity.snapshot_interval": 5,
        "identity.drift_threshold": 0.08,
        "identity.ema_alpha": 0.1,
        "identity.cooldown_cycles": 3,
    },
}
