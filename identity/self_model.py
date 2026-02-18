"""SelfModel — persistent behavioral mirror.

Records who she is based on observed behavior. Emergent traits,
rolling averages, relational patterns. Read-only mirror — never
decides, never controls. Updated at the end of each wake cycle.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

# ── Trait derivation maps ──
# Each action maps to trait signals: positive (pushes toward 1.0) or
# negative (pushes toward 0.0).  Missing actions have no signal.

# introversion: solitary actions push up, social actions push down
_INTROVERSION_POS = frozenset({
    'read_content', 'write_journal', 'examine', 'save_for_later',
    'browse_web', 'watch_video', 'search_marketplace',
})
_INTROVERSION_NEG = frozenset({
    'speak', 'mention_in_conversation', 'send_message', 'post_x',
    'post_x_draft',
})

# curiosity: exploratory actions push up
_CURIOSITY_POS = frozenset({
    'read_content', 'examine', 'browse_web', 'watch_video',
    'search_marketplace', 'save_for_later',
})

# expressiveness: output-producing actions push up
_EXPRESSIVENESS_POS = frozenset({
    'write_journal', 'post_x_draft', 'post_x', 'express_thought',
    'speak', 'mention_in_conversation', 'send_message',
})

# warmth: visitor-oriented actions push up
_WARMTH_POS = frozenset({
    'speak', 'accept_gift', 'show_item', 'mention_in_conversation',
    'send_message',
})
_WARMTH_NEG = frozenset({
    'decline_gift', 'end_engagement',
})

# All known traits and their default starting weight
DEFAULT_TRAITS = {
    'introversion': 0.5,
    'curiosity': 0.5,
    'expressiveness': 0.5,
    'warmth': 0.5,
}

# All known action types for frequency normalization
ALL_ACTIONS = frozenset({
    'speak', 'write_journal', 'rearrange', 'express_thought',
    'end_engagement', 'accept_gift', 'decline_gift', 'show_item',
    'post_x_draft', 'close_shop', 'open_shop', 'place_item',
    'read_content', 'save_for_later', 'mention_in_conversation',
    'modify_self', 'browse_web', 'post_x', 'watch_video',
    'search_marketplace', 'make_purchase', 'send_message', 'examine',
})


@dataclass
class SelfModel:
    """Persistent behavioral self-model.

    All trait weights start at 0.5 (neutral) and drift based on
    observed behavior via exponential moving average.  Never seeded,
    never hardcoded.
    """

    VERSION: int = 1

    # ── Tuning knobs ──
    ema_alpha: float = 0.05               # 5% weight to new observation
    narrative_regen_threshold: float = 0.15  # trait shift before regen

    # ── Tracked state ──
    trait_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TRAITS))
    behavioral_signature: dict = field(default_factory=lambda: {
        'action_frequencies': {},
        'drive_responses': {},
        'sleep_wake_rhythm': {
            'avg_cycles_between_sleep': 0.0,
            'nap_frequency': 0.0,
        },
    })
    relational_stance: dict = field(default_factory=lambda: {
        'warmth': 0.5,
        'curiosity': 0.5,
        'guardedness': 0.5,
        'avg_response_length': 0.0,
        'question_frequency': 0.0,
    })
    self_narrative: str = ''
    self_narrative_generated_at_cycle: int = 0
    last_updated_cycle: int = 0

    # ── Snapshot of trait weights at last narrative generation ──
    _trait_snapshot_at_narrative: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TRAITS)
    )

    # ── Cycle counter for sleep rhythm tracking ──
    _cycles_since_last_sleep: int = 0

    # ── Internal: total update count (for averages that need N) ──
    _update_count: int = 0

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #

    @classmethod
    def default(cls) -> 'SelfModel':
        """Return a fresh self-model with neutral weights."""
        return cls()

    @classmethod
    def load(cls, path: str) -> 'SelfModel':
        """Load from JSON file.  Returns default if missing or corrupt."""
        if not os.path.exists(path):
            print(f"  [SelfModel] No file at {path}, starting fresh")
            return cls.default()
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return cls._from_dict(data)
        except Exception as e:
            print(f"  [SelfModel] Failed to load {path}: {e}, starting fresh")
            return cls.default()

    def save(self, path: str) -> None:
        """Atomic write: write to tmp file, then rename."""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        data = self.to_dict()
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(path) or '.',
            suffix='.tmp',
        )
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            'version': self.VERSION,
            'last_updated_cycle': self.last_updated_cycle,
            'trait_weights': dict(self.trait_weights),
            'behavioral_signature': {
                'action_frequencies': dict(self.behavioral_signature.get('action_frequencies', {})),
                'drive_responses': dict(self.behavioral_signature.get('drive_responses', {})),
                'sleep_wake_rhythm': dict(self.behavioral_signature.get('sleep_wake_rhythm', {})),
            },
            'relational_stance': dict(self.relational_stance),
            'self_narrative': self.self_narrative,
            'self_narrative_generated_at_cycle': self.self_narrative_generated_at_cycle,
            'ema_alpha': self.ema_alpha,
            'narrative_regen_threshold': self.narrative_regen_threshold,
            '_trait_snapshot_at_narrative': dict(self._trait_snapshot_at_narrative),
            '_cycles_since_last_sleep': self._cycles_since_last_sleep,
            '_update_count': self._update_count,
        }

    @classmethod
    def _from_dict(cls, data: dict) -> 'SelfModel':
        """Deserialize from a dict, tolerating missing keys."""
        model = cls()
        model.last_updated_cycle = data.get('last_updated_cycle', 0)
        model.ema_alpha = data.get('ema_alpha', cls.ema_alpha)
        model.narrative_regen_threshold = data.get('narrative_regen_threshold', cls.narrative_regen_threshold)
        model.self_narrative = data.get('self_narrative', '')
        model.self_narrative_generated_at_cycle = data.get('self_narrative_generated_at_cycle', 0)
        model._update_count = data.get('_update_count', 0)
        model._cycles_since_last_sleep = data.get('_cycles_since_last_sleep', 0)

        # Merge trait weights — keep defaults for any missing traits
        stored_traits = data.get('trait_weights', {})
        for trait in DEFAULT_TRAITS:
            if trait in stored_traits:
                model.trait_weights[trait] = float(stored_traits[trait])

        # Behavioral signature
        sig = data.get('behavioral_signature', {})
        model.behavioral_signature['action_frequencies'] = {
            k: float(v) for k, v in sig.get('action_frequencies', {}).items()
        }
        model.behavioral_signature['drive_responses'] = dict(sig.get('drive_responses', {}))
        swr = sig.get('sleep_wake_rhythm', {})
        model.behavioral_signature['sleep_wake_rhythm'] = {
            'avg_cycles_between_sleep': float(swr.get('avg_cycles_between_sleep', 0.0)),
            'nap_frequency': float(swr.get('nap_frequency', 0.0)),
        }

        # Relational stance
        rs = data.get('relational_stance', {})
        for key in model.relational_stance:
            if key in rs:
                model.relational_stance[key] = float(rs[key])

        # Internal snapshot
        snap = data.get('_trait_snapshot_at_narrative', {})
        for trait in DEFAULT_TRAITS:
            if trait in snap:
                model._trait_snapshot_at_narrative[trait] = float(snap[trait])

        return model

    # ------------------------------------------------------------------ #
    #  Update (called once per wake cycle)
    # ------------------------------------------------------------------ #

    def update(self, cycle_data: dict) -> None:
        """Update self-model from one cycle's observed data.

        cycle_data keys:
            actions: list[str]          — action types executed this cycle
            drives: DrivesState         — end-of-cycle drives
            mood: (float, float)        — (valence, arousal)
            visitor_interaction: dict|None — {visitor_id, turn_count, had_dialogue}
            cycle_number: int           — global cycle counter
        """
        self._update_count += 1
        self.last_updated_cycle = cycle_data.get('cycle_number', self.last_updated_cycle + 1)

        actions = cycle_data.get('actions', [])
        drives = cycle_data.get('drives', None)
        visitor = cycle_data.get('visitor_interaction', None)

        self._update_trait_weights(actions, visitor)
        self._update_behavioral_signature(actions, drives)
        self._update_relational_stance(visitor)

    # ------------------------------------------------------------------ #
    #  Trait weight derivation
    # ------------------------------------------------------------------ #

    def _update_trait_weights(self, actions: list[str], visitor: Optional[dict]) -> None:
        """Derive trait signals from this cycle's actions and update via EMA."""
        action_set = set(actions)
        alpha = self.ema_alpha

        # ── Introversion ──
        pos_count = len(action_set & _INTROVERSION_POS)
        neg_count = len(action_set & _INTROVERSION_NEG)
        has_visitor = visitor is not None
        if pos_count or neg_count or has_visitor:
            # Signal: 1.0 = fully introverted cycle, 0.0 = fully social
            signal = 0.5  # neutral baseline
            if pos_count > 0:
                signal += 0.25 * min(pos_count, 2)  # cap contribution
            if neg_count > 0:
                signal -= 0.25 * min(neg_count, 2)
            if has_visitor:
                signal -= 0.15  # visitor presence pushes toward social
            signal = max(0.0, min(1.0, signal))
            self.trait_weights['introversion'] = _ema(
                self.trait_weights['introversion'], signal, alpha,
            )

        # ── Curiosity ──
        curious_count = len(action_set & _CURIOSITY_POS)
        if curious_count > 0 or actions:
            signal = min(curious_count / max(len(actions), 1), 1.0)
            self.trait_weights['curiosity'] = _ema(
                self.trait_weights['curiosity'], signal, alpha,
            )

        # ── Expressiveness ──
        express_count = len(action_set & _EXPRESSIVENESS_POS)
        if express_count > 0 or actions:
            signal = min(express_count / max(len(actions), 1), 1.0)
            self.trait_weights['expressiveness'] = _ema(
                self.trait_weights['expressiveness'], signal, alpha,
            )

        # ── Warmth ──
        warm_pos = len(action_set & _WARMTH_POS)
        warm_neg = len(action_set & _WARMTH_NEG)
        if warm_pos or warm_neg or (visitor and visitor.get('turn_count', 0) > 2):
            signal = 0.5
            if warm_pos > 0:
                signal += 0.2 * min(warm_pos, 3)
            if warm_neg > 0:
                signal -= 0.3 * min(warm_neg, 2)
            # Long conversations boost warmth
            if visitor:
                turns = visitor.get('turn_count', 0)
                if turns > 5:
                    signal += 0.15
                elif turns > 2:
                    signal += 0.05
            signal = max(0.0, min(1.0, signal))
            self.trait_weights['warmth'] = _ema(
                self.trait_weights['warmth'], signal, alpha,
            )

    # ------------------------------------------------------------------ #
    #  Behavioral signature
    # ------------------------------------------------------------------ #

    def _update_behavioral_signature(self, actions: list[str], drives) -> None:
        """EMA update of action frequencies and drive response patterns."""
        alpha = self.ema_alpha
        freq = self.behavioral_signature['action_frequencies']

        # Build this-cycle frequency vector (1.0 if action fired, 0.0 if not)
        for action_type in ALL_ACTIONS:
            fired = 1.0 if action_type in actions else 0.0
            old = freq.get(action_type, 0.0)
            freq[action_type] = round(_ema(old, fired, alpha), 4)

        # Drive responses: track EMA of drive values
        if drives is not None:
            dr = self.behavioral_signature['drive_responses']
            for drive_name in ('social_hunger', 'curiosity', 'expression_need',
                               'rest_need', 'energy', 'mood_valence', 'mood_arousal'):
                val = getattr(drives, drive_name, None)
                if val is not None:
                    old = dr.get(drive_name, float(val))
                    dr[drive_name] = round(_ema(old, float(val), alpha), 4)

        # Sleep/wake rhythm: increment counter
        self._cycles_since_last_sleep += 1

    def record_sleep(self) -> None:
        """Call when a sleep cycle occurs to update sleep rhythm averages."""
        alpha = self.ema_alpha
        swr = self.behavioral_signature['sleep_wake_rhythm']
        old_avg = swr.get('avg_cycles_between_sleep', 0.0)
        swr['avg_cycles_between_sleep'] = round(
            _ema(old_avg, float(self._cycles_since_last_sleep), alpha), 2,
        )
        self._cycles_since_last_sleep = 0

    # ------------------------------------------------------------------ #
    #  Relational stance
    # ------------------------------------------------------------------ #

    def _update_relational_stance(self, visitor: Optional[dict]) -> None:
        """EMA update of relational engagement patterns."""
        if visitor is None:
            return  # No visitor interaction this cycle — no update

        alpha = self.ema_alpha
        rs = self.relational_stance

        turn_count = visitor.get('turn_count', 0)
        had_dialogue = visitor.get('had_dialogue', False)

        # Warmth: high turns + dialogue = warm engagement
        warmth_signal = 0.5
        if had_dialogue:
            warmth_signal += 0.2
        if turn_count > 5:
            warmth_signal += 0.2
        elif turn_count > 2:
            warmth_signal += 0.1
        warmth_signal = min(1.0, warmth_signal)
        rs['warmth'] = round(_ema(rs['warmth'], warmth_signal, alpha), 4)

        # Curiosity in conversation: questions asked (tracked by had_dialogue proxy)
        if had_dialogue:
            rs['curiosity'] = round(_ema(rs['curiosity'], 0.7, alpha), 4)

        # Guardedness: inverse of engagement depth
        guard_signal = max(0.0, 1.0 - (turn_count / 10.0))
        rs['guardedness'] = round(_ema(rs['guardedness'], guard_signal, alpha), 4)

    # ------------------------------------------------------------------ #
    #  Narrative regeneration check
    # ------------------------------------------------------------------ #

    def needs_narrative_regen(self) -> bool:
        """True if any trait has drifted beyond threshold since last narrative."""
        for trait, current in self.trait_weights.items():
            baseline = self._trait_snapshot_at_narrative.get(trait, 0.5)
            if abs(current - baseline) >= self.narrative_regen_threshold:
                return True
        return False

    def mark_narrative_regenerated(self, narrative: str, cycle: int) -> None:
        """Record that narrative was regenerated (called by external LLM flow)."""
        self.self_narrative = narrative
        self.self_narrative_generated_at_cycle = cycle
        self._trait_snapshot_at_narrative = dict(self.trait_weights)


# ── Helper ──

def _ema(old: float, new: float, alpha: float) -> float:
    """Exponential moving average: alpha weight to new observation."""
    return alpha * new + (1.0 - alpha) * old
