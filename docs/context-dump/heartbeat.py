"""Heartbeat — the shopkeeper's heartbeat. Drives all cycles."""

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Optional

import db
from db import JST
import clock
from models.event import Event
from models.state import DrivesState
from models.pipeline import ValidatorState, ValidatedOutput, MotorPlan, HabitBoost
from pipeline.sensorium import build_perceptions, Perception
from pipeline.gates import perception_gate
from pipeline.affect import apply_affect_lens
from pipeline.hypothalamus import update_drives, clamp
from pipeline.thalamus import route
from pipeline.hippocampus import recall
from pipeline.cortex import cortex_call
from pipeline.validator import validate
from pipeline.basal_ganglia import select_actions, check_habits
from pipeline.body import execute_body, END_ENGAGEMENT_LINES
from pipeline.output import process_output
from pipeline.enrich import fetch_url_metadata
from pipeline.arbiter import (
    ArbiterFocus, decide_cycle_focus, update_arbiter_after_cycle,
)
from prompt.self_context import assemble_self_context
from pipeline.ambient import fetch_ambient_context
from pipeline.enrich import fetch_readable_text
from sleep import sleep_cycle, nap_consolidate
from pipeline.day_memory import maybe_record_moment
from identity.self_model import SelfModel

# Type for stage callbacks: async fn(stage_name, stage_data)
StageCallback = Optional[Callable[[str, dict], Awaitable[None]]]


@dataclass
class CycleResult:
    """Result of a single autonomous cycle for simulation/logging."""
    cycle_type: str           # idle | rest | nap | express | consume | thread | news
    focus_channel: str        # arbiter channel that was chosen
    detail: str               # human-readable summary
    actions: list[str]        # action types executed
    sleep_seconds: int        # how long to sleep/advance before next cycle
    dialogue: str | None = None
    internal_monologue: str = ''
    log: dict = field(default_factory=dict)


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

# DEPRECATED: Diegetic mappings — moved to prompt/self_context.py (TASK-060)
# Kept here to avoid breaking any external imports.
_GAZE_MAP = {
    'at_visitor': 'at the visitor',
    'at_object': 'at something on the shelf',
    'away_thinking': 'away, thinking',
    'down': 'down',
    'window': 'out the window',
}

_ACTION_MAP = {
    'close_shop': 'closed the shop',
    'open_shop': 'opened the shop',
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
    """DEPRECATED — use prompt.self_context.assemble_self_context() instead.

    Kept for backward compatibility. TASK-060 replaced this with the unified
    self-context assembler. The main cycle now calls assemble_self_context()
    directly.
    """
    # Delegate to the new assembler for any remaining callers
    from prompt.self_context import assemble_self_context
    result = await assemble_self_context(visitor=visitor)
    return result if result else None


class Heartbeat:
    """The shopkeeper's heartbeat. Drives all cycles."""

    # Cycle interval bounds (seconds)
    INTERVAL_MIN = 10
    INTERVAL_MAX = 600
    INTERVAL_DEFAULT = 180  # 3 minutes

    def __init__(self):
        self.running = False
        self.pending_microcycle = asyncio.Event()
        self._wake_event = asyncio.Event()  # wake loop without triggering microcycle
        self._last_cycle_ts = clock.now_utc()
        self._last_creative_cycle_ts: Optional[datetime] = None
        self._last_sleep_date: Optional[str] = None  # ISO date string (restored from DB on start)
        self._last_fidget_behavior: Optional[str] = None
        self._recent_fidgets: list[tuple] = []  # (behavior_key, description, timestamp)
        self._cycle_log_subscribers: dict[str, asyncio.Queue] = {}
        self._loop_task = None
        self._stage_callback: StageCallback = None
        self._window_broadcast: Optional[Callable] = None
        self._error_backoff = 5
        self._arbiter_state: Optional[dict] = None  # loaded from DB on start
        self._last_ambient_fetch_ts: Optional[datetime] = None
        self._ambient_fetch_ok: bool = True  # assume ok until first failure
        self._last_feed_fetch_ts: Optional[datetime] = None
        self._cycle_interval: int = self.INTERVAL_DEFAULT
        self._last_resonance: bool = False  # previous cycle's resonance flag
        self._consecutive_idle: int = 0  # TASK-046: in-memory idle counter for arousal decay
        self._last_expression_taken: bool = False  # TASK-046: previous cycle had expression action
        self._recent_action_types: list[str] = []  # last 3 cycle primary actions
        self._self_model: Optional[SelfModel] = None  # TASK-061: persistent behavioral mirror

        # TASK-057: Set X draft cooldown (30 min between posts at gate level)
        from pipeline.action_registry import ACTION_REGISTRY
        if 'post_x_draft' in ACTION_REGISTRY:
            ACTION_REGISTRY['post_x_draft'].cooldown_seconds = 1800

    def get_cycle_interval(self) -> int:
        """Return the current cycle interval in seconds."""
        return self._cycle_interval

    def set_cycle_interval(self, seconds: int, *, persist: bool = True) -> int:
        """Set cycle interval (clamped to INTERVAL_MIN..INTERVAL_MAX). Returns actual value.

        Wakes the main loop so the new interval takes effect immediately
        rather than waiting for the current (possibly longer) sleep to finish.
        When persist=True (default), saves to DB so the value survives restarts.
        """
        self._cycle_interval = max(self.INTERVAL_MIN, min(self.INTERVAL_MAX, seconds))
        print(f"  [Heartbeat] Cycle interval set to {self._cycle_interval}s")
        # Wake the loop so it re-sleeps with the new interval
        self._wake_event.set()
        if persist:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_cycle_interval())
            except RuntimeError:
                pass  # no event loop (tests, sync context) — skip persistence
        return self._cycle_interval

    async def _persist_cycle_interval(self):
        """Save current cycle interval to DB."""
        try:
            await db.set_setting('cycle_interval', str(self._cycle_interval))
        except Exception as e:
            print(f"  [Heartbeat] Failed to persist cycle interval: {e}")

    def _get_cycle_interval(self, channel: str) -> int:
        """Return sleep seconds for the given channel, based on operator-set interval.

        Applies a jitter of +/-25% to avoid perfectly periodic cycles.
        Rest cycles use 2.5x the base interval (they're meant to be longer).
        """
        base = self._cycle_interval
        if channel == 'rest':
            base = int(base * 2.5)
        # Jitter: 75%-125% of base, clamped to bounds
        lo = max(self.INTERVAL_MIN, int(base * 0.75))
        hi = max(lo + 1, min(self.INTERVAL_MAX * 3, int(base * 1.25)))
        return random.randint(lo, hi)

    def set_window_broadcast(self, cb: Callable):
        """Set callback for broadcasting to window viewers."""
        self._window_broadcast = cb

    def _pick_fidget_behavior(self) -> tuple[str, str]:
        """Pick a fidget behavior while avoiding immediate repetition."""
        choices = FIDGET_BEHAVIORS
        if self._last_fidget_behavior:
            filtered = [b for b in FIDGET_BEHAVIORS if b[0] != self._last_fidget_behavior]
            if filtered:
                choices = filtered
        behavior, description = random.choice(choices)
        self._last_fidget_behavior = behavior
        # Track for body_memory — visitor may reference these later
        self._recent_fidgets.append((behavior, description, clock.now_utc()))
        self._recent_fidgets = self._recent_fidgets[-5:]  # keep last 5
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
        # Load arbiter state from DB (persisted across restarts)
        try:
            self._arbiter_state = await db.load_arbiter_state()
        except Exception:
            # arbiter_state table may not exist yet (pre-migration DB)
            self._arbiter_state = {
                'consume_count_today': 0, 'news_engage_count_today': 0,
                'thread_focus_count_today': 0, 'express_count_today': 0,
                'last_consume_ts': None, 'last_news_engage_ts': None,
                'last_thread_focus_ts': None, 'last_express_ts': None,
                'recent_focus_keywords': [], 'current_date_jst': '',
            }
        # Restore cycle interval from DB (survives restarts)
        try:
            saved = await db.get_setting('cycle_interval')
            if saved is not None:
                self.set_cycle_interval(int(saved), persist=False)
        except Exception:
            pass  # settings table may not exist yet — use default
        # Restore last sleep date from DB (survives restarts)
        try:
            saved_sleep = await db.get_setting('last_sleep_date')
            if saved_sleep is not None:
                self._last_sleep_date = saved_sleep
                print(f"  [Heartbeat] Restored last_sleep_date: {saved_sleep}")
        except Exception:
            pass
        # TASK-061: Load persistent self-model
        self._self_model = SelfModel.load('identity/self_model.json')
        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        self.running = False
        self.pending_microcycle.set()  # wake up any wait
        self._wake_event.set()  # also wake interruptible_sleep
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
        """Sleep that wakes immediately when a microcycle is scheduled or wake_event fires."""
        self._wake_event.clear()
        # Wake on either: microcycle scheduled OR interval changed (wake_event)
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(self.pending_microcycle.wait()),
                asyncio.create_task(self._wake_event.wait()),
            ],
            timeout=seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancel any still-pending waiters
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _is_sleep_window(self) -> bool:
        """Check if current time is 03:00-06:00 JST."""
        now_jst = clock.now()
        return 3 <= now_jst.hour < 6

    def _should_sleep(self) -> bool:
        """Check if we should run the sleep cycle."""
        if not self._is_sleep_window():
            return False
        today_jst = clock.now().date().isoformat()
        return self._last_sleep_date != today_jst

    def _creative_cooldown_elapsed(self) -> bool:
        """True if >=2 hours since last creative cycle."""
        if self._last_creative_cycle_ts is None:
            return True
        elapsed = (clock.now_utc() - self._last_creative_cycle_ts).total_seconds()
        return elapsed >= 7200  # 2 hours

    def _creative_overdue(self) -> bool:
        """True if >4 hours since last creative cycle."""
        if self._last_creative_cycle_ts is None:
            return True
        elapsed = (clock.now_utc() - self._last_creative_cycle_ts).total_seconds()
        return elapsed >= 14400  # 4 hours

    async def _main_loop(self):
        # Run one idle cycle immediately on startup — but ONLY if not already
        # engaged (terminal pre-sets engagement + schedules a microcycle for
        # the visitor_connect event; running an idle cycle here would eat that
        # event from the inbox before the microcycle gets to it).
        if self.running and not self.pending_microcycle.is_set():
            if self._should_sleep():
                print("  [Heartbeat] Sleep window on startup — skipping startup cycle")
            else:
                engagement = await db.get_engagement_state()
                if engagement.status != 'engaged':
                    try:
                        await self.run_cycle('idle')
                    except Exception as e:
                        print(f"  [Heartbeat] Startup cycle error: {e}")

        while self.running:
            try:
                # ── Microcycle has top priority (even during sleep window) ──
                # This MUST be checked before sleep to prevent deferral loops
                # from starving visitor messages during 03:00-06:00 JST.
                if self.pending_microcycle.is_set():
                    self.pending_microcycle.clear()
                    if not self.running:
                        break
                    await self.run_cycle('micro')
                    self._consecutive_idle = 0  # TASK-046: visitor event resets idle counter
                    continue

                # ── Sleep cycle check ──
                if self._should_sleep():
                    try:
                        await self._emit_stage('sleep', {'status': 'entering_sleep'})
                        ran = await sleep_cycle()
                        if ran >= 0:
                            self._last_sleep_date = clock.now().date().isoformat()
                            try:
                                await db.set_setting('last_sleep_date', self._last_sleep_date)
                            except Exception:
                                pass  # best-effort persist
                            # TASK-061: Record sleep event in self-model
                            if self._self_model is not None:
                                try:
                                    self._self_model.record_sleep()
                                    self._self_model.save('identity/self_model.json')
                                except Exception as e:
                                    print(f"  [SelfModel] Sleep record failed: {e}")
                            await self._emit_stage('sleep', {'status': 'woke_up'})
                        else:
                            # Deferred — do NOT stamp _last_sleep_date.
                            # Will retry on next loop iteration.
                            await self._emit_stage('sleep', {'status': 'deferred'})
                    except Exception as e:
                        print(f"  [Heartbeat] Sleep cycle error: {e}")
                    await self._interruptible_sleep(60)
                    continue

                # ── Sleep window idle (sleep done or deferred, no microcycle) ──
                if self._is_sleep_window():
                    await self._interruptible_sleep(60)
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
                            idle_s = (clock.now_utc() - engagement.last_activity).total_seconds()
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
                        cooldown_s = (clock.now_utc() - engagement.last_activity).total_seconds()
                        if cooldown_s > 120:
                            await db.update_engagement_state(
                                status='none', visitor_id=None, turn_count=0
                            )
                    await self._interruptible_sleep(30)
                    continue

                # ── Visitors present but not engaged ──
                # Someone is in the shop (browsing/waiting) but she hasn't
                # spoken to them yet. Wait for messages with shorter timeout,
                # then fall through to autonomous if no one speaks.
                visitors = await db.get_visitors_present()
                if visitors:
                    try:
                        await asyncio.wait_for(
                            self.pending_microcycle.wait(),
                            timeout=random.randint(15, 45)
                        )
                        continue  # microcycle triggered
                    except asyncio.TimeoutError:
                        if self.pending_microcycle.is_set():
                            continue
                        # Fall through to autonomous — she does her own thing
                        # while visitors browse

                # ── Autonomous behavior (no visitor engaged) ──
                # She lives whether anyone is watching or not.
                result = await self.run_one_cycle(drives)
                if clock.is_simulating():
                    clock.advance(result.sleep_seconds)
                else:
                    await self._interruptible_sleep(result.sleep_seconds)

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

    async def run_one_cycle(self, drives: DrivesState = None) -> CycleResult:
        """Execute one autonomous cycle and return the result.

        Extracted from _main_loop for simulation mode. In production,
        _main_loop calls this and then sleeps. In simulation, the caller
        advances the virtual clock by result.sleep_seconds instead.
        """
        if drives is None:
            drives = await db.get_drives_state()

        # ── Ambient weather fetch (every 30-60 min, retry after 5 min on failure) ──
        if not clock.is_simulating():
            elapsed = (
                (clock.now_utc() - self._last_ambient_fetch_ts).total_seconds()
                if self._last_ambient_fetch_ts else float('inf')
            )
            stale_threshold = 2400 if self._ambient_fetch_ok else 300
            if elapsed > stale_threshold:
                try:
                    ambient = await fetch_ambient_context()
                    self._last_ambient_fetch_ts = clock.now_utc()
                    if ambient:
                        self._ambient_fetch_ok = True
                        weather_event = Event(
                            event_type='ambient_weather',
                            source='ambient',
                            payload={
                                'condition': ambient.condition,
                                'temp_c': ambient.temp_c,
                                'diegetic_text': ambient.diegetic_text,
                                'season': ambient.season,
                                'season_text': ambient.season_text,
                            },
                            channel='ambient',
                            salience_base=0.1,
                            ttl_hours=1.0,
                        )
                        await db.append_event(weather_event)
                        if ambient.mood_nudge != 0:
                            drives.mood_valence = max(-1.0, min(1.0,
                                drives.mood_valence + ambient.mood_nudge))
                            await db.save_drives_state(drives)
                    else:
                        self._ambient_fetch_ok = False
                except Exception as e:
                    print(f"  [Heartbeat] Ambient fetch error: {e}")
                    self._last_ambient_fetch_ts = clock.now_utc()
                    self._ambient_fetch_ok = False

        # ── Feed ingestion (every hour, skip in simulation — pool is pre-loaded) ──
        if not clock.is_simulating():
            feed_stale = (
                self._last_feed_fetch_ts is None
                or (clock.now_utc() - self._last_feed_fetch_ts).total_seconds() > 3600
            )
            if feed_stale:
                try:
                    from feed_ingester import run_feed_ingestion
                    await run_feed_ingestion()
                    self._last_feed_fetch_ts = clock.now_utc()
                    await db.expire_pool_items()
                    from config.feeds import MAX_POOL_UNSEEN
                    await db.cap_unseen_pool(max_unseen=MAX_POOL_UNSEEN)
                except Exception as e:
                    print(f"  [Heartbeat] Feed ingestion error: {e}")

        # Let the arbiter decide focus
        focus = await decide_cycle_focus(drives, self._arbiter_state)

        cycle_log = {}
        if focus.channel == 'idle':
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
                detail = f'fidget: {description}'
            else:
                cycle_log = await self.run_cycle('idle')
                detail = cycle_log.get('internal_monologue', '')[:60] or 'idle cycle'
            sleep_seconds = self._get_cycle_interval('idle')

        elif focus.channel == 'rest':
            cycle_log = await self.run_cycle('rest')
            detail = 'resting'
            sleep_seconds = self._get_cycle_interval('rest')

        else:
            # Focused cycle (express, consume, thread, news)

            # Consume enrichment: fetch readable text + mark pool item seen
            if focus.channel == 'consume' and focus.payload:
                pool_id = focus.payload.get('pool_id')
                url = focus.payload.get('url')
                if url:
                    try:
                        readable = await fetch_readable_text(url)
                        focus.payload['readable_text'] = readable
                    except Exception:
                        focus.payload['readable_text'] = ''
                if pool_id:
                    await db.update_pool_item(
                        pool_id, status='seen',
                        seen_at=clock.now_utc(),
                    )

            # News: mark pool item seen
            if focus.channel == 'news' and focus.payload:
                pool_id = focus.payload.get('pool_id')
                if pool_id:
                    await db.update_pool_item(
                        pool_id, status='seen',
                        seen_at=clock.now_utc(),
                    )

            cycle_log = await self.run_cycle(focus.pipeline_mode,
                                             focus_context=focus)
            # Update arbiter counters + persist
            update_arbiter_after_cycle(self._arbiter_state, focus)
            if focus.channel == 'express':
                self._last_creative_cycle_ts = clock.now_utc()
            await db.save_arbiter_state(self._arbiter_state)
            detail = cycle_log.get('internal_monologue', '')[:60] or focus.channel
            sleep_seconds = self._get_cycle_interval('focused')

        # TASK-046: Update consecutive idle counter for arousal decay
        is_idle = focus.channel == 'idle'
        if is_idle:
            self._consecutive_idle += 1
        else:
            self._consecutive_idle = 0

        return CycleResult(
            cycle_type=cycle_log.get('routing_focus', focus.channel),
            focus_channel=focus.channel,
            detail=detail,
            actions=cycle_log.get('actions', []),
            sleep_seconds=sleep_seconds,
            dialogue=cycle_log.get('dialogue'),
            internal_monologue=cycle_log.get('internal_monologue', ''),
            log=cycle_log,
        )

    async def start_for_simulation(self):
        """Initialize for simulation mode. No event loop task or TCP listener."""
        self.running = True
        try:
            self._arbiter_state = await db.load_arbiter_state()
        except Exception:
            self._arbiter_state = {
                'consume_count_today': 0, 'news_engage_count_today': 0,
                'thread_focus_count_today': 0, 'express_count_today': 0,
                'last_consume_ts': None, 'last_news_engage_ts': None,
                'last_thread_focus_ts': None, 'last_express_ts': None,
                'recent_focus_keywords': [], 'current_date_jst': '',
            }
        # TASK-061: Load persistent self-model
        self._self_model = SelfModel.load('identity/self_model.json')

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

    async def run_cycle(self, mode: str,
                        focus_context: Optional[ArbiterFocus] = None) -> dict:
        """Execute one full cycle. Emits stage callbacks progressively.

        focus_context: Optional arbiter focus for autonomous cycles.
        When present, a focus perception is injected at salience=1.0
        and non-visitor perceptions are capped at 0.3.
        """

        cycle_id = str(uuid.uuid4())[:8]
        start_time = clock.now_utc()

        # 0a. Refresh parameter cache for this cycle
        await db.refresh_params_cache()

        # 0. Ghost engagement sanity check — if engaged but no active visitor,
        # clear immediately. Prevents stuck-in-conversation loops when a
        # WebSocket drops without sending visitor_disconnect.
        engagement_check = await db.get_engagement_state()
        if engagement_check.status == 'engaged':
            visitors = await db.get_visitors_present()
            has_active = any(
                v.visitor_id == engagement_check.visitor_id
                for v in visitors
            )
            if not has_active:
                print(f"  [Heartbeat] Cleared ghost engagement — "
                      f"no active visitor for {engagement_check.visitor_id}")
                await db.update_engagement_state(
                    status='none', visitor_id=None, turn_count=0
                )

        # 1. Read inbox (mark read AFTER successful execution to prevent event loss)
        unread = await db.inbox_get_unread()

        # 2. Load and update drives (persist inside transaction below)
        drives = await db.get_drives_state()
        drives_before = drives.copy()  # snapshot for day_memory delta computation
        elapsed = (start_time - self._last_cycle_ts).total_seconds() / 3600.0
        self._last_cycle_ts = start_time
        cortex_flags = {}
        if self._last_resonance:
            cortex_flags['resonance'] = True
        if self._recent_action_types and len(set(self._recent_action_types)) == len(self._recent_action_types):
            # All recent actions are different — novelty
            cortex_flags['action_variety'] = True
        # TASK-046: Build cycle context for drive-mood coupling
        has_engagement_events = any(
            e.event_type in ('visitor_speech', 'visitor_connect')
            for e in unread
        )
        cycle_context = {
            'consecutive_idle': self._consecutive_idle,
            'engaged_this_cycle': has_engagement_events,
            'expression_taken': self._last_expression_taken,
        }
        drives, feelings = await update_drives(
            drives, elapsed, unread, cortex_flags or None,
            cycle_context=cycle_context,
        )

        # 3. Sensorium: events → perceptions
        perceptions = await build_perceptions(
            unread, drives, self._recent_fidgets,
            focus_context=focus_context,
        )

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

        # ── Focus injection: cap non-focus non-visitor perceptions ──
        if focus_context and focus_context.payload:
            for p in perceptions:
                if p.salience < 1.0 and not p.p_type.startswith('visitor_'):
                    p.salience = min(p.salience, 0.3)
            # Re-sort after salience capping
            perceptions.sort(key=lambda p: p.salience, reverse=True)

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

        # ── Mode binding: arbiter focus overrides Thalamus unless visitor is primary ──
        if focus_context and routing.focus and not routing.focus.p_type.startswith('visitor_'):
            routing.cycle_type = focus_context.pipeline_mode
            # Override token budget if arbiter specified one
            if focus_context.token_budget_hint:
                routing.token_budget = focus_context.token_budget_hint

        # Creative cooldown gate: block express routing if < 2hrs since last creative
        # Exception: arbiter thread focus explicitly requests express — don't override it
        if routing.cycle_type == 'express' and not self._creative_cooldown_elapsed() and not focus_context:
            routing.cycle_type = 'idle'
            routing.token_budget = 3000

        # Force express if > 4hrs since last creative (only for non-arbiter idle cycles)
        if (mode == 'idle' and not focus_context
                and self._creative_overdue() and drives.expression_need > 0.3):
            routing.cycle_type = 'express'

        # 6. Hippocampus: recall
        memory_chunks = await recall(routing.memory_requests)

        # ── STAGE: Thalamus ──
        await self._emit_stage('thalamus', {
            'routing_focus': routing.cycle_type,
            'token_budget': routing.token_budget,
            'memory_count': len(memory_chunks),
        })

        # ── Habit check: reflexive habits auto-fire, generative habits boost ──
        habit_result = await check_habits(drives, engagement)
        habit_boost = None  # set if generative habit matched
        if isinstance(habit_result, HabitBoost):
            habit_boost = habit_result
            print(f"  [Heartbeat] Habit boost (generative): {habit_boost.action} "
                  f"(strength {habit_boost.strength:.2f})")
        habit_plan = habit_result if isinstance(habit_result, MotorPlan) else None
        if habit_plan:
            print(f"  [Heartbeat] Habit auto-fire: {habit_plan.actions[0].action}")
            await self._emit_stage('cortex', {
                'internal_monologue': '(habit — reflex, not thought)',
                'resonance': False,
            })
            await self._emit_stage('actions', {
                'approved': [a.action for a in habit_plan.actions],
                'dropped': [],
                '_entropy_warning': None,
            })

            habit_log = {
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
                'token_budget': 0,
                'memory_count': len(memory_chunks),
                'internal_monologue': '(habit — reflex, not thought)',
                'dialogue': None,
                'expression': 'neutral',
                'body_state': 'sitting',
                'gaze': 'away_thinking',
                'actions': [a.action for a in habit_plan.actions],
                'dropped': [],
                'next_cycle_hints': [],
                'resonance': False,
                '_entropy_warning': None,
                'intentions_count': 0,
                'habit_fired': True,
            }

            # Build minimal validated for body/output compatibility
            habit_validated = ValidatedOutput(
                internal_monologue='(habit — reflex, not thought)',
                expression='neutral',
                body_state='sitting',
                gaze='away_thinking',
            )

            async with db.transaction():
                await db.save_drives_state(drives)
                body_output = await execute_body(habit_plan, habit_validated,
                                                 visitor_id, cycle_id=cycle_id)
                await process_output(body_output, habit_validated, visitor_id,
                                     motor_plan=habit_plan, cycle_id=cycle_id,
                                     elapsed_hours=elapsed)
                for event in unread:
                    await db.inbox_mark_read(event.id)
                await db.log_cycle(habit_log)

            await self._emit_stage('dialogue', {
                'dialogue': None,
                'expression': 'neutral',
            })

            self._error_backoff = 5

            for sub_id, q in list(self._cycle_log_subscribers.items()):
                while q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                try:
                    q.put_nowait(habit_log)
                except asyncio.QueueFull:
                    pass

            return habit_log

        # 7a. Real-dollar budget check (TASK-050)
        # If daily dollar budget is spent, skip cortex entirely and rest.
        # No naps, no partial restore — budget is budget. She's done for the day.
        budget_info = await db.get_budget_remaining()
        print(f"  [Heartbeat] Budget: ${budget_info['spent']:.3f} / "
              f"${budget_info['budget']:.2f} "
              f"(${budget_info['remaining']:.3f} remaining)")
        if budget_info['remaining'] <= 0:
            print(f"  [Heartbeat] Resting — budget spent "
                  f"(${budget_info['spent']:.2f}/${budget_info['budget']:.2f})")

            # Update energy display value (derived from budget)
            drives.energy = 0.0

            rest_log = {
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
                'routing_focus': 'rest',
                'token_budget': 0,
                'memory_count': len(memory_chunks),
                'internal_monologue': f'(resting — budget spent ${budget_info["spent"]:.2f}/${budget_info["budget"]:.2f})',
                'dialogue': None,
                'expression': 'neutral',
                'body_state': 'resting',
                'gaze': 'down',
                'actions': [],
                'dropped': [],
                'next_cycle_hints': [],
                'resonance': False,
                '_entropy_warning': None,
                'intentions_count': 0,
                'budget_exhausted': True,
            }

            async with db.transaction():
                await db.save_drives_state(drives)
                for event in unread:
                    await db.inbox_mark_read(event.id)
                await db.log_cycle(rest_log)

            await self._emit_stage('dialogue', {
                'dialogue': None,
                'expression': 'neutral',
            })

            self._error_backoff = 5

            for sub_id, q in list(self._cycle_log_subscribers.items()):
                while q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                try:
                    q.put_nowait(rest_log)
                except asyncio.QueueFull:
                    pass

            return rest_log

        # Update energy display value: remaining / budget ratio
        drives.energy = clamp(budget_info['remaining'] / budget_info['budget'])

        # 7. URL enrichment (if gift detected — URLs captured before gate)
        gift_meta = None
        if _gift_urls:
            gift_meta = await fetch_url_metadata(_gift_urls[0])

        # 7b. Self-context: unified self-awareness snapshot (TASK-060)
        # Replaces the old build_self_state() — assembles identity, state,
        # recent behavior, and temporal awareness into a single block.
        self_state = await assemble_self_context(
            visitor=visitor,
            habit_boost=habit_boost,
        )

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
        val_state = ValidatorState(
            hands_held_item=visitor.hands_state if visitor else None,
            cycle_type=routing.cycle_type,
            energy=drives.energy,
            turn_count=engagement.turn_count,
            trust_level=visitor.trust_level if visitor else 'stranger',
        )
        validated = validate(cortex_output, val_state)

        # Pass pool_id through for executor pool status tracking
        if focus_context and focus_context.payload and focus_context.payload.get('pool_id'):
            validated.focus_pool_id = focus_context.payload['pool_id']

        # 9b. Habit boost: add +0.3 impulse to matching intention
        if habit_boost and validated.intentions:
            for intention in validated.intentions:
                if intention.action == habit_boost.action:
                    intention.impulse = min(1.0, intention.impulse + 0.3)
                    break

        # Journal deferred — the desire to write builds up
        if validated.journal_deferred:
            drives.expression_need = min(1.0, drives.expression_need + 0.15)

        # ── STAGE: Cortex ──
        await self._emit_stage('cortex', {
            'internal_monologue': validated.internal_monologue,
            'resonance': validated.resonance,
        })

        # ── STAGE: Actions ──
        approved = validated.approved_actions
        dropped = validated.dropped_actions
        if approved or dropped:
            await self._emit_stage('actions', {
                'approved': [a.type for a in approved],
                'dropped': [{'reason': d.reason} for d in dropped],
                '_entropy_warning': validated.entropy_warning,
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
            'internal_monologue': validated.internal_monologue,
            'dialogue': validated.dialogue,
            'expression': validated.expression,
            'body_state': validated.body_state,
            'gaze': validated.gaze,
            'actions': [a.type for a in approved],
            'dropped': [{'reason': d.reason} for d in dropped],
            'next_cycle_hints': validated.next_cycle_hints,
            'resonance': validated.resonance,
            '_entropy_warning': validated.entropy_warning,
            'intentions_count': len(validated.intentions),
        }

        # Gate resonance to engage-mode cycles only.
        # The LLM often returns resonance=True during idle/autonomous cycles
        # (thinking alone, reading content). True resonance requires a visitor.
        # Without this gate, resonance drains social_hunger by 0.30 per event
        # (0.15 in output.py + 0.15 in hypothalamus next cycle) and the
        # homeostatic pull (+0.006/cycle) cannot recover.
        if validated.resonance and mode != 'engage':
            validated.resonance = False

        # Cache resonance for next cycle's hypothalamus
        self._last_resonance = validated.resonance

        # Track primary action type for variety detection
        primary_action = approved[0].type if approved else routing.cycle_type
        self._recent_action_types.append(primary_action)
        self._recent_action_types = self._recent_action_types[-3:]

        # Build context for basal ganglia gate checks
        bg_context = {
            'visitor_present': visitor_id is not None,
            'turn_count': engagement.turn_count,
            'mode': mode,
            'cycle_type': routing.cycle_type,
        }

        async with db.transaction():
            await db.save_drives_state(drives)
            motor_plan = await select_actions(validated, drives, context=bg_context)
            body_output = await execute_body(motor_plan, validated, visitor_id, cycle_id=cycle_id)
            await process_output(body_output, validated, visitor_id,
                                 motor_plan=motor_plan, cycle_id=cycle_id,
                                 elapsed_hours=elapsed)
            for event in unread:
                await db.inbox_mark_read(event.id)
            await db.log_cycle(log)

        # TASK-046: Track whether expression happened for next cycle's frustration check
        _EXPRESSION_ACTIONS = {'action_speak', 'write_journal', 'post_x_draft',
                               'rearrange', 'express_thought'}
        self._last_expression_taken = any(
            ar.success and ar.action in _EXPRESSION_ACTIONS
            for ar in body_output.executed
        ) if body_output.executed else False

        # ── STAGE: Dialogue (last) ──
        await self._emit_stage('dialogue', {
            'dialogue': validated.dialogue,
            'expression': validated.expression,
        })

        # ── STAGE: End Engagement (if she ended the conversation) ──
        for action in approved:
            if action.type == 'end_engagement':
                reason = action.detail.get('reason', 'natural')
                farewell = END_ENGAGEMENT_LINES.get(reason, END_ENGAGEMENT_LINES['natural'])
                await self._emit_stage('end_engagement', {
                    'reason': reason,
                    'farewell': farewell,
                })
        self._error_backoff = 5  # reset backoff on successful cycle

        # ── Window broadcast: push scene update to web viewers ──
        if self._window_broadcast:
            try:
                from window_state import build_cycle_broadcast
                room = await db.get_room_state()
                ambient = {'condition': room.weather}
                shelf_items = await db.get_shelf_assignments()
                broadcast_msg = await build_cycle_broadcast(
                    cycle_log=log,
                    drives=drives,
                    ambient=ambient,
                    focus=routing.focus if routing else None,
                    engagement=engagement,
                    clock_now=datetime.now(timezone.utc),
                    shelf_items=shelf_items,
                    shop_status=room.shop_status,
                )
                await self._window_broadcast(broadcast_msg)
            except Exception as e:
                print(f"  [WindowBroadcast] Error: {e}")
        # ── Day Memory: record salient moment from this cycle ──
        try:
            cycle_context = self._build_cycle_context(
                cycle_id=cycle_id, mode=mode, visitor=visitor,
                visitor_id=visitor_id, engagement=engagement,
                drives_before=drives_before, drives_after=drives,
                unread=unread, routing=routing, validated=validated,
                focus_context=focus_context, body_output=body_output,
            )
            await maybe_record_moment(validated.to_dict(), cycle_context)
        except Exception as e:
            # Day memory failure must not break the main cycle
            print(f"  [DayMemory] Error recording moment: {e}")

        # ── Self-Model Update: record behavioral observation ──
        if self._self_model is not None:
            try:
                visitor_interaction = None
                if visitor_id and visitor:
                    visitor_interaction = {
                        'visitor_id': visitor_id,
                        'turn_count': engagement.turn_count,
                        'had_dialogue': validated.dialogue is not None,
                    }
                self._self_model.update(cycle_data={
                    'actions': [ar.action for ar in body_output.executed if ar.success],
                    'drives': drives,
                    'mood': (drives.mood_valence, drives.mood_arousal),
                    'visitor_interaction': visitor_interaction,
                    'cycle_number': self._self_model.last_updated_cycle + 1,
                })
                self._self_model.save('identity/self_model.json')
            except Exception as e:
                print(f"  [SelfModel] Update failed: {e}")

        # ── TASK-062: Drift detection ──
        try:
            from identity.drift import get_detector
            drift_result = await get_detector().check(log, drives)
            if drift_result and drift_result.level != 'none':
                print(f"  [Drift] level={drift_result.level} "
                      f"composite={drift_result.composite:.3f}")
        except Exception as e:
            # Drift failure must not break the main cycle
            print(f"  [Drift] Error: {e}")

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
            ts=clock.now_utc(),
            content=content,
            features={'is_silence': True, 'idle_seconds': idle_seconds},
            salience=salience,
        )

    def _build_cycle_context(
        self,
        cycle_id: str,
        mode: str,
        visitor,
        visitor_id: str,
        engagement,
        drives_before,
        drives_after,
        unread: list,
        routing,
        validated: ValidatedOutput,
        focus_context=None,
        body_output=None,
    ) -> dict:
        """Build the cycle_context dict for day memory moment extraction.

        Deterministic — no DB calls, no LLM.
        """
        # Compute max drive delta
        drive_fields = [
            'social_hunger', 'curiosity', 'expression_need',
            'rest_need', 'energy', 'mood_valence', 'mood_arousal',
        ]
        max_delta = 0.0
        for field in drive_fields:
            before_val = getattr(drives_before, field, 0.0)
            after_val = getattr(drives_after, field, 0.0)
            max_delta = max(max_delta, abs(after_val - before_val))

        # Contradiction: internal_shift_candidate is emitted by the PREVIOUS
        # cycle's hippocampus_consolidate, so it appears in THIS cycle's unread.
        # The salience boost lands one cycle late — acceptable because the
        # follow-up cycle is contextually adjacent to the contradiction.
        had_contradiction = any(
            e.event_type == 'internal_shift_candidate' for e in unread
        )

        # Abrupt end: visitor disconnected with few turns
        is_abrupt_end = (
            any(e.event_type == 'visitor_disconnect' for e in unread)
            and engagement.turn_count < 3
        )

        # Silence moment: idle cycle after long silence during engagement
        is_silence_moment = False
        if (mode in ('ambient', 'idle')
                and engagement.status == 'engaged'
                and engagement.last_activity is not None):
            idle_s = (clock.now_utc() - engagement.last_activity).total_seconds()
            is_silence_moment = idle_s > 1800

        # TASK-053: Arbiter channel — 'consume'/'news' are channels, not modes.
        # The pipeline mode for 'consume' is 'engage', for 'news' is 'idle',
        # so checking mode alone misses content-consumption cycles.
        channel = focus_context.channel if focus_context else None

        # TASK-053: Internal conflict detection.
        # Conflict = high arousal + negative valence (emotional tension),
        # OR actions were dropped due to suppression (frustrated intent).
        emotional_tension = (
            drives_after.mood_arousal > 0.7 and drives_after.mood_valence < 0.3
        )
        suppressed_actions = [
            d for d in validated.dropped_actions
            if d.reason and 'suppress' in d.reason.lower()
        ]
        has_conflict = emotional_tension or bool(suppressed_actions)

        # Build a specific description so day_memory records what actually
        # happened, not a generic "something felt off" fallback.
        conflict_description = None
        if has_conflict:
            parts = []
            if emotional_tension:
                arousal_pct = int(drives_after.mood_arousal * 100)
                valence_pct = int(drives_after.mood_valence * 100)
                # Pick the most notable drive to name
                drive_notes = []
                if drives_after.social_hunger > 0.6:
                    drive_notes.append(
                        f"social hunger at {int(drives_after.social_hunger * 100)}%"
                    )
                if drives_after.expression_need > 0.6:
                    drive_notes.append(
                        f"expression need at {int(drives_after.expression_need * 100)}%"
                    )
                if drives_after.energy < 0.3:
                    drive_notes.append(
                        f"energy low at {int(drives_after.energy * 100)}%"
                    )
                if drive_notes:
                    parts.append(
                        f"Tension building — {', '.join(drive_notes[:2])}"
                        f" (arousal {arousal_pct}%, valence {valence_pct}%)"
                    )
                else:
                    parts.append(
                        f"Emotional tension — arousal {arousal_pct}%"
                        f" but valence only {valence_pct}%"
                    )
            if suppressed_actions:
                action_names = [d.action.type.replace('_', ' ')
                                for d in suppressed_actions[:3]]
                parts.append(
                    f"Suppressed {len(suppressed_actions)} action(s): "
                    + ', '.join(action_names)
                )
            conflict_description = '; '.join(parts)

        # TASK-053: Executed action types from body output.
        # The salience function needs to know what actually ran, not just what
        # cortex requested. body_output.executed has ActionResult with .action str.
        executed_action_types = []
        if body_output and body_output.executed:
            executed_action_types = [
                ar.action for ar in body_output.executed if ar.success
            ]

        return {
            'cycle_id': cycle_id,
            'mode': mode,
            'channel': channel,
            'visitor_id': visitor_id,
            'visitor_name': visitor.name if visitor else None,
            'trust_level': visitor.trust_level if visitor else 'stranger',
            'event_ids': [e.id for e in unread],
            'max_drive_delta': max_delta,
            'mood_valence': drives_after.mood_valence,
            'had_contradiction': had_contradiction,
            'has_internal_conflict': has_conflict,
            'internal_conflict_description': conflict_description,
            'is_abrupt_end': is_abrupt_end,
            'is_silence_moment': is_silence_moment,
            'is_novel_topic': False,  # deferred to Phase 2
            'turn_count': engagement.turn_count,
            'executed_action_types': executed_action_types,
        }

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
