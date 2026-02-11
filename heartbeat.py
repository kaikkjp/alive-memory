"""Heartbeat — the shopkeeper's heartbeat. Drives all cycles."""

import asyncio
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Optional

import db
from db import JST
from models.event import Event
from models.state import DrivesState
from pipeline.sensorium import build_perceptions, Perception
from pipeline.gates import perception_gate
from pipeline.affect import apply_affect_lens
from pipeline.hypothalamus import update_drives
from pipeline.thalamus import route
from pipeline.hippocampus import recall
from pipeline.cortex import cortex_call
from pipeline.validator import validate
from pipeline.executor import execute
from pipeline.enrich import fetch_url_metadata
from sleep import sleep_cycle

# Type for stage callbacks: async fn(stage_name, stage_data)
StageCallback = Optional[Callable[[str, dict], Awaitable[None]]]

# Body-only fidget behaviors (no LLM cost)
FIDGET_BEHAVIORS = [
    ("adjusts_glasses", "She adjusts her glasses."),
    ("looks_at_object", "She picks up something from the shelf and turns it over."),
    ("sips_tea", "She takes a sip of tea."),
    ("turns_page", "She turns a page."),
    ("glances_at_window", "She glances toward the window."),
    ("touches_shelf", "Her fingers trail along the shelf edge."),
    ("examines_item", "She holds something up to the light, studying it."),
]

# Diegetic mappings for self_state assembly
_GAZE_MAP = {
    'at_visitor': 'at the visitor',
    'at_object': 'at something on the shelf',
    'away_thinking': 'away, thinking',
    'down': 'down',
    'window': 'out the window',
}

_ACTION_MAP = {
    'close_shop': 'closed the shop',
    'write_journal': 'wrote in your journal',
    'accept_gift': 'accepted a gift',
    'decline_gift': 'declined a gift',
    'show_item': 'showed an item',
    'place_item': 'put something down',
    'rearrange': 'rearranged something',
    'post_x_draft': 'drafted a post',
    'end_engagement': 'ended the conversation',
}


def _truncate_at_word(text: str, max_chars: int = 60) -> str:
    """Truncate at word boundary, append '...' if shortened."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(' ', 1)[0]
    return truncated + '...'


async def build_self_state(visitor, unread: list) -> str | None:
    """Assemble diegetic self-state from last cycle_log + current room.

    Returns a text block for the Cortex prompt, or None on first boot.
    ~50-80 tokens. No LLM cost.
    """
    last = await db.get_last_cycle_log()
    if not last:
        return None  # first boot — no previous cycle

    room = await db.get_room_state()

    parts = ['RIGHT NOW:']

    # Body position
    parts.append(f'  You are {last["body_state"]}.')

    # Expression (skip if neutral — it's the default)
    if last['expression'] and last['expression'] != 'neutral':
        parts.append(f'  Your expression is {last["expression"]}.')

    # Gaze
    gaze_text = _GAZE_MAP.get(last['gaze'], last['gaze'])
    parts.append(f"  You're looking {gaze_text}.")

    # Shop status (from live room_state, not stale cycle_log)
    parts.append(f'  The shop is {room.shop_status}.')

    # Hands
    if visitor and visitor.hands_state:
        parts.append(f"  You're holding {visitor.hands_state}.")

    # Last action(s)
    if last['actions']:
        action_key = last['actions'][0]  # most significant
        action_text = _ACTION_MAP.get(action_key, action_key.replace('_', ' '))
        parts.append(f'  You just {action_text}.')

    # Internal monologue (truncate at word boundary)
    if last['internal_monologue']:
        thought = _truncate_at_word(last['internal_monologue'])
        parts.append(f'  You were thinking: "{thought}"')

    # Next cycle hints — suppress if engagement boundary crossed
    has_engagement_change = any(
        getattr(e, 'event_type', None) in ('visitor_connect', 'visitor_disconnect')
        for e in unread
    )
    hints = last['next_cycle_hints']
    if hints and isinstance(hints, list) and not has_engagement_change:
        hint = hints[0]
        if isinstance(hint, str) and hint:
            parts.append(f'  You were about to {hint}.')

    return '\n'.join(parts)


class Heartbeat:
    """The shopkeeper's heartbeat. Drives all cycles."""

    def __init__(self):
        self.running = False
        self.pending_microcycle = asyncio.Event()
        self._last_cycle_ts = datetime.now(timezone.utc)
        self._last_creative_cycle_ts: Optional[datetime] = None
        self._last_sleep_date: Optional[str] = None  # ISO date string
        self._last_fidget_behavior: Optional[str] = None
        self._cycle_log_subscribers: dict[str, asyncio.Queue] = {}
        self._loop_task = None
        self._stage_callback: StageCallback = None
        self._error_backoff = 5

    def _pick_fidget_behavior(self) -> tuple[str, str]:
        """Pick a fidget behavior while avoiding immediate repetition."""
        choices = FIDGET_BEHAVIORS
        if self._last_fidget_behavior:
            filtered = [b for b in FIDGET_BEHAVIORS if b[0] != self._last_fidget_behavior]
            if filtered:
                choices = filtered
        behavior, description = random.choice(choices)
        self._last_fidget_behavior = behavior
        return behavior, description

    def set_stage_callback(self, cb: StageCallback):
        """Set a callback that fires after each pipeline stage."""
        self._stage_callback = cb

    async def _emit_stage(self, stage: str, data: dict):
        """Fire stage callback if set."""
        if self._stage_callback:
            await self._stage_callback(stage, data)

    async def start(self):
        self.running = True
        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        self.running = False
        self.pending_microcycle.set()  # wake up any wait
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass

    async def _interruptible_sleep(self, seconds: float):
        """Sleep that wakes immediately when a microcycle is scheduled."""
        try:
            await asyncio.wait_for(self.pending_microcycle.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _is_sleep_window(self) -> bool:
        """Check if current time is 03:00-06:00 JST."""
        now_jst = datetime.now(JST)
        return 3 <= now_jst.hour < 6

    def _should_sleep(self) -> bool:
        """Check if we should run the sleep cycle."""
        if not self._is_sleep_window():
            return False
        today_jst = datetime.now(JST).date().isoformat()
        return self._last_sleep_date != today_jst

    def _creative_cooldown_elapsed(self) -> bool:
        """True if >=2 hours since last creative cycle."""
        if self._last_creative_cycle_ts is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_creative_cycle_ts).total_seconds()
        return elapsed >= 7200  # 2 hours

    def _creative_overdue(self) -> bool:
        """True if >4 hours since last creative cycle."""
        if self._last_creative_cycle_ts is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_creative_cycle_ts).total_seconds()
        return elapsed >= 14400  # 4 hours

    async def _main_loop(self):
        # Run one idle cycle immediately on startup — but ONLY if not already
        # engaged (terminal pre-sets engagement + schedules a microcycle for
        # the visitor_connect event; running an idle cycle here would eat that
        # event from the inbox before the microcycle gets to it).
        if self.running and not self.pending_microcycle.is_set():
            engagement = await db.get_engagement_state()
            if engagement.status != 'engaged':
                try:
                    await self.run_cycle('idle')
                except Exception as e:
                    print(f"  [Heartbeat] Startup cycle error: {e}")

        while self.running:
            try:
                # ── Sleep cycle check ──
                if self._should_sleep():
                    self._last_sleep_date = datetime.now(JST).date().isoformat()
                    try:
                        await self._emit_stage('sleep', {'status': 'entering_sleep'})
                        await sleep_cycle()
                        await self._emit_stage('sleep', {'status': 'woke_up'})
                    except Exception as e:
                        print(f"  [Heartbeat] Sleep cycle error: {e}")
                    # After sleep, continue the loop
                    await self._interruptible_sleep(60)
                    continue

                # During sleep window, only process microcycles (visitor ACK)
                if self._is_sleep_window():
                    if self.pending_microcycle.is_set():
                        self.pending_microcycle.clear()
                        if not self.running:
                            break
                        await self.run_cycle('micro')
                    else:
                        await self._interruptible_sleep(60)
                    continue

                # ── Microcycle has priority (visitor triggered) ──
                if self.pending_microcycle.is_set():
                    self.pending_microcycle.clear()
                    if not self.running:
                        break
                    await self.run_cycle('micro')
                    continue

                engagement = await db.get_engagement_state()
                drives = await db.get_drives_state()

                if engagement.status == 'engaged':
                    # ── Engaged: silence awareness + message wait ──
                    # Wait 30-90s for visitor message, or fire ambient cycle
                    try:
                        await asyncio.wait_for(
                            self.pending_microcycle.wait(),
                            timeout=random.randint(30, 90)
                        )
                        # Microcycle triggered — loop back
                        continue
                    except asyncio.TimeoutError:
                        # Before running ambient/silence cycles, check if a
                        # microcycle arrived in the gap (race between terminal
                        # sleep + schedule_microcycle and this timeout path).
                        # Also check inbox for unread visitor events — if the
                        # visitor spoke but the microcycle hasn't been scheduled
                        # yet, don't let an ambient cycle eat the speech event.
                        if self.pending_microcycle.is_set():
                            continue  # loop back, microcycle takes priority
                        unread = await db.inbox_get_unread()
                        has_visitor_event = any(
                            e.event_type in ('visitor_speech', 'visitor_connect', 'visitor_disconnect')
                            for e in unread
                        )
                        if has_visitor_event:
                            continue  # visitor event pending, don't steal it

                        # No message — run silence-aware ambient cycle
                        engagement = await db.get_engagement_state()
                        if engagement.last_activity:
                            idle_s = (datetime.now(timezone.utc) - engagement.last_activity).total_seconds()
                            if idle_s > 300:
                                # 5+ min silence: she can disengage naturally
                                await self.run_cycle('ambient')
                            elif idle_s > 30:
                                # Silence awareness: fidget or speak
                                await self.run_silence_cycle(engagement, drives, idle_s)
                            # else: normal pause, just wait more
                        continue

                elif engagement.status == 'cooldown':
                    # In cooldown after ending engagement — wait 2 min then go idle
                    if engagement.last_activity:
                        cooldown_s = (datetime.now(timezone.utc) - engagement.last_activity).total_seconds()
                        if cooldown_s > 120:
                            await db.update_engagement_state(
                                status='none', visitor_id=None, turn_count=0
                            )
                    await self._interruptible_sleep(30)
                    continue

                # ── Autonomous behavior (no visitor engaged) ──
                # She lives whether anyone is watching or not.

                # Check shop status — reopen if rested enough
                room = await db.get_room_state()
                if room.shop_status == 'closed' and drives.energy > 0.5:
                    await db.update_room_state(shop_status='open')

                # Creative cycle (expensive, 2-4 hour cadence)
                if self._creative_overdue() or (
                    self._creative_cooldown_elapsed() and drives.expression_need > 0.5
                ):
                    await self.run_cycle('express')
                    self._last_creative_cycle_ts = datetime.now(timezone.utc)
                    await self._interruptible_sleep(random.randint(120, 600))

                elif drives.rest_need > 0.7:
                    await self.run_cycle('rest')
                    await self._interruptible_sleep(random.randint(300, 1800))

                else:
                    # Ambient idle — 50% body-only (zero LLM cost), 50% full cycle
                    if random.random() < 0.5:
                        behavior, description = self._pick_fidget_behavior()
                        body_event = Event(
                            event_type='action_body',
                            source='self',
                            payload={
                                'expression': 'neutral',
                                'body_state': behavior,
                                'gaze': random.choice(['away_thinking', 'window', 'down']),
                            },
                        )
                        await db.append_event(body_event)
                        await self._emit_stage('dialogue', {
                            'dialogue': None,
                            'expression': 'neutral',
                            'body_description': description,
                        })
                    else:
                        await self.run_cycle('idle')
                    await self._interruptible_sleep(random.randint(120, 600))

            except asyncio.CancelledError:
                break
            except RuntimeError as e:
                if 'ANTHROPIC_API_KEY' in str(e):
                    print(f"\n  \033[91m[Error]\033[0m {e}")
                    self.running = False
                    break
                print(f"  [Heartbeat Error] {e}")
                await asyncio.sleep(self._error_backoff)
                self._error_backoff = min(60, self._error_backoff * 2)
            except Exception as e:
                print(f"  [Heartbeat Error] {e}")
                await asyncio.sleep(self._error_backoff)
                self._error_backoff = min(60, self._error_backoff * 2)

    async def schedule_microcycle(self):
        """Signal that a microcycle should run."""
        self.pending_microcycle.set()

    async def run_silence_cycle(self, engagement, drives, idle_seconds: float):
        """Handle visitor silence — fidget or speak."""

        # Probability: 30% full Cortex cycle, 70% body-only fidget
        if random.random() < 0.30:
            # Full cycle with silence perception
            await self.run_cycle('ambient')
        else:
            # Body-only fidget (zero LLM cost)
            behavior, description = self._pick_fidget_behavior()
            body_event = Event(
                event_type='action_body',
                source='self',
                payload={
                    'expression': 'neutral',
                    'body_state': behavior,
                    'gaze': random.choice(['at_object', 'away_thinking', 'window', 'down']),
                },
            )
            await db.append_event(body_event)

            await self._emit_stage('dialogue', {
                'dialogue': None,
                'expression': 'neutral',
                'body_description': description,
            })

            # Silence affects drives
            visitor = await db.get_visitor(engagement.visitor_id) if engagement.visitor_id else None
            trust = visitor.trust_level if visitor else 'stranger'

            d = await db.get_drives_state()
            if trust == 'stranger':
                # Stranger silence: social battery recovers slightly
                d.social_hunger = max(0.0, d.social_hunger + 0.02)
            elif trust == 'familiar':
                # Familiar silence: comfortable
                d.mood_valence = min(1.0, d.mood_valence + 0.05)
            # Long silence after any exchange: contemplative
            if idle_seconds > 120:
                d.expression_need = min(1.0, d.expression_need + 0.03)
            await db.save_drives_state(d)

    async def run_cycle(self, mode: str) -> dict:
        """Execute one full cycle. Emits stage callbacks progressively."""

        cycle_id = str(uuid.uuid4())[:8]
        start_time = datetime.now(timezone.utc)

        # 1. Read inbox (mark read AFTER successful execution to prevent event loss)
        unread = await db.inbox_get_unread()

        # 2. Load and update drives (persist inside transaction below)
        drives = await db.get_drives_state()
        elapsed = (start_time - self._last_cycle_ts).total_seconds() / 3600.0
        self._last_cycle_ts = start_time
        drives, feelings = await update_drives(drives, elapsed, unread)

        # 3. Sensorium: events → perceptions
        perceptions = await build_perceptions(unread, drives)

        # For ambient cycles during engagement, inject silence perception
        if mode == 'ambient':
            engagement = await db.get_engagement_state()
            if engagement.status == 'engaged' and engagement.last_activity:
                idle_s = (start_time - engagement.last_activity).total_seconds()
                silence_p = self._build_silence_perception(idle_s)
                if silence_p:
                    perceptions.append(silence_p)
                    perceptions.sort(key=lambda p: p.salience, reverse=True)
                    perceptions = perceptions[:4]

        # Capture gift URLs before gate strips them
        _gift_urls = []
        if perceptions and perceptions[0].features.get('contains_gift'):
            _gift_urls = perceptions[0].features.get('urls', [])

        # 4. Perception gate + affect lens
        engagement = await db.get_engagement_state()
        visitor = None
        visitor_id = None
        if engagement.visitor_id:
            visitor = await db.get_visitor(engagement.visitor_id)
            visitor_id = engagement.visitor_id
        elif perceptions:
            for p in perceptions:
                if p.source.startswith('visitor:'):
                    vid = p.source.split(':')[1]
                    visitor = await db.get_visitor(vid)
                    visitor_id = vid
                    break

        perceptions = perception_gate(perceptions, visitor_id)
        perceptions = apply_affect_lens(perceptions, drives)

        # ── STAGE: Sensorium ──
        await self._emit_stage('sensorium', {
            'focus_salience': round(perceptions[0].salience, 2) if perceptions else 0,
            'focus_type': perceptions[0].p_type if perceptions else 'none',
        })

        # ── STAGE: Drives ──
        await self._emit_stage('drives', {
            'social_hunger': round(drives.social_hunger, 2),
            'curiosity': round(drives.curiosity, 2),
            'expression_need': round(drives.expression_need, 2),
            'rest_need': round(drives.rest_need, 2),
            'energy': round(drives.energy, 2),
            'mood_valence': round(drives.mood_valence, 2),
            'mood_arousal': round(drives.mood_arousal, 2),
        })

        # 5. Thalamus: route
        routing = await route(perceptions, drives, engagement, visitor)

        # Creative cooldown gate: block express routing if < 2hrs since last creative
        if routing.cycle_type == 'express' and not self._creative_cooldown_elapsed():
            routing.cycle_type = 'idle'
            routing.token_budget = 3000

        # Force express if > 4hrs since last creative
        if mode == 'idle' and self._creative_overdue() and drives.expression_need > 0.3:
            routing.cycle_type = 'express'

        # 6. Hippocampus: recall
        memory_chunks = await recall(routing.memory_requests)

        # ── STAGE: Thalamus ──
        await self._emit_stage('thalamus', {
            'routing_focus': routing.cycle_type,
            'token_budget': routing.token_budget,
            'memory_count': len(memory_chunks),
        })

        # 7. URL enrichment (if gift detected — URLs captured before gate)
        gift_meta = None
        if _gift_urls:
            gift_meta = await fetch_url_metadata(_gift_urls[0])

        # 7b. Self-state: what she was just doing (deterministic, no LLM)
        self_state = await build_self_state(visitor, unread)

        # 8. Cortex (THE LLM CALL)
        conversation = []
        if visitor_id:
            conversation = await db.get_recent_conversation(visitor_id)
        cortex_output = await cortex_call(
            routing, perceptions, memory_chunks,
            conversation, drives, visitor, gift_meta,
            self_state=self_state,
        )

        # 9. Validate
        state = {
            'hands_held_item': visitor.hands_state if visitor else None,
            'cycle_type': routing.cycle_type,
            'energy': drives.energy,
            'turn_count': engagement.turn_count,
        }
        validated = validate(cortex_output, state)

        # ── STAGE: Cortex ──
        await self._emit_stage('cortex', {
            'internal_monologue': validated.get('internal_monologue', ''),
            'resonance': validated.get('resonance', False),
        })

        # ── STAGE: Actions ──
        approved = validated.get('_approved_actions', [])
        dropped = validated.get('_dropped_actions', [])
        if approved or dropped:
            await self._emit_stage('actions', {
                'approved': [a.get('type', '') for a in approved],
                'dropped': [{'reason': d['reason']} for d in dropped],
                '_entropy_warning': validated.get('_entropy_warning'),
            })

        # 10. Execute + mark inbox read + log cycle — all in one transaction
        #     so a mid-cycle failure rolls back cleanly (no partial state).
        log = {
            'id': cycle_id,
            'mode': mode,
            'drives': {
                'social_hunger': round(drives.social_hunger, 2),
                'curiosity': round(drives.curiosity, 2),
                'expression_need': round(drives.expression_need, 2),
                'rest_need': round(drives.rest_need, 2),
                'energy': round(drives.energy, 2),
                'mood_valence': round(drives.mood_valence, 2),
                'mood_arousal': round(drives.mood_arousal, 2),
            },
            'focus_salience': round(routing.focus.salience, 2) if routing.focus else 0,
            'focus_type': routing.focus.p_type if routing.focus else 'none',
            'routing_focus': routing.cycle_type,
            'token_budget': routing.token_budget,
            'memory_count': len(memory_chunks),
            'internal_monologue': validated.get('internal_monologue', ''),
            'dialogue': validated.get('dialogue'),
            'expression': validated.get('expression', 'neutral'),
            'body_state': validated.get('body_state', 'sitting'),
            'gaze': validated.get('gaze', 'at_visitor'),
            'actions': [a.get('type', '') for a in approved],
            'dropped': [{'reason': d['reason']} for d in dropped],
            'next_cycle_hints': validated.get('next_cycle_hints', []),
            'resonance': validated.get('resonance', False),
            '_entropy_warning': validated.get('_entropy_warning'),
        }

        async with db.transaction():
            await db.save_drives_state(drives)
            await execute(validated, visitor_id)
            for event in unread:
                await db.inbox_mark_read(event.id)
            await db.log_cycle(log)

        # ── STAGE: Dialogue (last) ──
        await self._emit_stage('dialogue', {
            'dialogue': validated.get('dialogue'),
            'expression': validated.get('expression', 'neutral'),
        })

        # ── STAGE: End Engagement (if she ended the conversation) ──
        for action in approved:
            if action.get('type') == 'end_engagement':
                from pipeline.executor import END_ENGAGEMENT_LINES
                reason = action.get('detail', {}).get('reason', 'natural')
                farewell = END_ENGAGEMENT_LINES.get(reason, END_ENGAGEMENT_LINES['natural'])
                await self._emit_stage('end_engagement', {
                    'reason': reason,
                    'farewell': farewell,
                })
        self._error_backoff = 5  # reset backoff on successful cycle

        # Broadcast to all subscribers (bounded queues, drop oldest if full)
        for sub_id, q in list(self._cycle_log_subscribers.items()):
            while q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                q.put_nowait(log)
            except asyncio.QueueFull:
                pass

        return log

    def _build_silence_perception(self, idle_seconds: float) -> Optional[Perception]:
        """Build a silence perception based on how long visitor has been quiet."""
        if idle_seconds < 30:
            return None  # normal pause
        elif idle_seconds < 60:
            content = "A pause in conversation."
            salience = 0.2
        elif idle_seconds < 120:
            content = "They've gone quiet."
            salience = 0.4
        elif idle_seconds < 300:
            content = "They're just... here. Watching."
            salience = 0.6
        else:
            content = "The silence has become the conversation."
            salience = 0.7

        return Perception(
            p_type='visitor_silence',
            source='ambient',
            ts=datetime.now(timezone.utc),
            content=content,
            features={'is_silence': True, 'idle_seconds': idle_seconds},
            salience=salience,
        )

    def subscribe_cycle_logs(self, subscriber_id: str, maxsize: int = 50) -> asyncio.Queue:
        """Register a subscriber for cycle logs. Returns their personal queue."""
        q = asyncio.Queue(maxsize=maxsize)
        self._cycle_log_subscribers[subscriber_id] = q
        return q

    def unsubscribe_cycle_logs(self, subscriber_id: str):
        """Remove a subscriber."""
        self._cycle_log_subscribers.pop(subscriber_id, None)

    async def wait_for_cycle_log(self, subscriber_id: str, timeout: float = 30.0) -> dict:
        """Wait for the next cycle log entry for a specific subscriber."""
        q = self._cycle_log_subscribers.get(subscriber_id)
        if not q:
            return None
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
