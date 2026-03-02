"""Tests for engine/bus.py and bus integration in heartbeat.py."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from bus import EventBus
from bus_types import TOPIC_CYCLE_COMPLETE, TOPIC_SCENE_UPDATE, TOPIC_STAGE_PROGRESS


# ---------------------------------------------------------------------------
# TestBroadcastPubSub
# ---------------------------------------------------------------------------

class TestBroadcastPubSub:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        q = bus.subscribe('t', 'sub1')
        bus.publish('t', {'a': 1})
        assert q.get_nowait() == {'a': 1}

    def test_fanout_to_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe('t', 's1')
        q2 = bus.subscribe('t', 's2')
        bus.publish('t', 'msg')
        assert q1.get_nowait() == 'msg'
        assert q2.get_nowait() == 'msg'

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        bus.unsubscribe('t', 's1')
        bus.publish('t', 'msg')
        assert q.empty()

    def test_drop_oldest_when_full(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1', maxsize=2)
        bus.publish('t', 'a')
        bus.publish('t', 'b')
        bus.publish('t', 'c')  # should drop 'a'
        assert q.get_nowait() == 'b'
        assert q.get_nowait() == 'c'
        assert q.empty()

    def test_empty_topic_noop(self):
        bus = EventBus()
        # Should not raise
        bus.publish('nonexistent', {'x': 1})

    def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count('t') == 0
        bus.subscribe('t', 's1')
        assert bus.subscriber_count('t') == 1
        bus.subscribe('t', 's2')
        assert bus.subscriber_count('t') == 2
        bus.unsubscribe('t', 's1')
        assert bus.subscriber_count('t') == 1

    def test_unsubscribe_nonexistent_is_noop(self):
        bus = EventBus()
        bus.unsubscribe('no-topic', 'no-sub')  # should not raise


# ---------------------------------------------------------------------------
# TestKeyedPubSub
# ---------------------------------------------------------------------------

class TestKeyedPubSub:
    def test_exact_key_match(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'alice', 's1')
        bus.publish_keyed('t', 'alice', 'msg')
        assert q.get_nowait() == 'msg'

    def test_no_cross_delivery(self):
        bus = EventBus()
        q_alice = bus.subscribe_keyed('t', 'alice', 's1')
        q_bob = bus.subscribe_keyed('t', 'bob', 's2')
        bus.publish_keyed('t', 'alice', 'for-alice')
        assert q_alice.get_nowait() == 'for-alice'
        assert q_bob.empty()

    def test_wildcard_receives_non_wildcard_publishes(self):
        bus = EventBus()
        q_star = bus.subscribe_keyed('t', '*', 'watcher')
        bus.publish_keyed('t', 'alice', 'msg1')
        bus.publish_keyed('t', 'bob', 'msg2')
        assert q_star.get_nowait() == 'msg1'
        assert q_star.get_nowait() == 'msg2'

    def test_wildcard_key_publish_no_double_delivery(self):
        """publish_keyed(key='*') delivers only to '*' subscribers, not all keys."""
        bus = EventBus()
        q_star = bus.subscribe_keyed('t', '*', 'watcher')
        q_alice = bus.subscribe_keyed('t', 'alice', 's1')
        bus.publish_keyed('t', '*', 'ambient')
        # '*' subscriber gets it via exact match
        assert q_star.get_nowait() == 'ambient'
        # 'alice' subscriber does NOT get it (not a broadcast)
        assert q_alice.empty()
        # '*' subscriber got it exactly once (no double delivery)
        assert q_star.empty()

    def test_unsubscribe_keyed(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'k', 's1')
        bus.unsubscribe_keyed('t', 'k', 's1')
        bus.publish_keyed('t', 'k', 'msg')
        assert q.empty()

    def test_drop_oldest_keyed(self):
        bus = EventBus()
        q = bus.subscribe_keyed('t', 'k', 's1', maxsize=2)
        bus.publish_keyed('t', 'k', 'a')
        bus.publish_keyed('t', 'k', 'b')
        bus.publish_keyed('t', 'k', 'c')
        assert q.get_nowait() == 'b'
        assert q.get_nowait() == 'c'

    def test_unsubscribe_keyed_nonexistent_is_noop(self):
        bus = EventBus()
        bus.unsubscribe_keyed('no-topic', 'no-key', 'no-sub')  # should not raise


# ---------------------------------------------------------------------------
# TestVisitorLock
# ---------------------------------------------------------------------------

class TestVisitorLock:
    def test_same_visitor_same_lock(self):
        bus = EventBus()
        lock1 = bus.visitor_lock('v1')
        lock2 = bus.visitor_lock('v1')
        assert lock1 is lock2

    def test_different_visitors_different_locks(self):
        bus = EventBus()
        lock1 = bus.visitor_lock('v1')
        lock2 = bus.visitor_lock('v2')
        assert lock1 is not lock2

    @pytest.mark.asyncio
    async def test_lock_serializes(self):
        bus = EventBus()
        lock = bus.visitor_lock('v1')
        order = []

        async def worker(label, delay):
            async with lock:
                order.append(f'{label}-start')
                await asyncio.sleep(delay)
                order.append(f'{label}-end')

        t1 = asyncio.create_task(worker('A', 0.05))
        await asyncio.sleep(0.01)  # ensure A starts first
        t2 = asyncio.create_task(worker('B', 0.01))
        await asyncio.gather(t1, t2)
        assert order == ['A-start', 'A-end', 'B-start', 'B-end']


# ---------------------------------------------------------------------------
# TestWait
# ---------------------------------------------------------------------------

class TestWait:
    @pytest.mark.asyncio
    async def test_returns_message(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        bus.publish('t', 'hello')
        result = await bus.wait(q, timeout=1.0)
        assert result == 'hello'

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        bus = EventBus()
        q = bus.subscribe('t', 's1')
        result = await bus.wait(q, timeout=0.05)
        assert result is None


# ---------------------------------------------------------------------------
# TestHeartbeatIntegration
# ---------------------------------------------------------------------------

class TestHeartbeatIntegration:
    def test_default_bus_exists(self):
        """Heartbeat creates a default bus in __init__."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        assert hb._bus is not None

    def test_set_bus_replaces_default(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        bus = EventBus()
        hb.set_bus(bus)
        assert hb._bus is bus

    @pytest.mark.asyncio
    async def test_set_bus_migrates_existing_subscribers(self):
        """Bus swap after subscribe_cycle_logs migrates queues to new bus."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('alice')
        # Swap to a new bus
        new_bus = EventBus()
        hb.set_bus(new_bus)
        # Publish on the new bus — alice should still receive
        log = {'visitor_id': 'alice', 'data': 'after-swap'}
        await hb._publish_cycle_log(log)
        result = await hb.wait_for_cycle_log('alice', timeout=1.0)
        assert result == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_to_bus(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb._bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, 'visitor-1', 'test')
        log = {'visitor_id': 'visitor-1', 'type': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_wildcard_subscriber(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb._bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, '*', 'watcher')
        log = {'visitor_id': 'visitor-1', 'type': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_publish_cycle_log_ambient_uses_wildcard_key(self):
        """Cycle with no visitor_id publishes with key='*'."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb._bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, '*', 'watcher')
        log = {'type': 'idle'}  # no visitor_id
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_subscribe_cycle_logs_uses_bus(self):
        """subscribe_cycle_logs delegates to bus.subscribe_keyed."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb.subscribe_cycle_logs('visitor-1')
        log = {'visitor_id': 'visitor-1', 'data': 'test'}
        await hb._publish_cycle_log(log)
        assert q.get_nowait() == log

    @pytest.mark.asyncio
    async def test_unsubscribe_cycle_logs_stops_delivery(self):
        """After unsubscribe, no more messages are delivered."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb.subscribe_cycle_logs('visitor-1')
        hb.unsubscribe_cycle_logs('visitor-1')
        log = {'visitor_id': 'visitor-1', 'data': 'test'}
        await hb._publish_cycle_log(log)
        assert q.empty()

    @pytest.mark.asyncio
    async def test_wait_for_cycle_log_returns_message(self):
        """wait_for_cycle_log returns the published log."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('visitor-1')
        log = {'visitor_id': 'visitor-1', 'data': 'test'}
        await hb._publish_cycle_log(log)
        result = await hb.wait_for_cycle_log('visitor-1', timeout=1.0)
        assert result == log

    @pytest.mark.asyncio
    async def test_wait_for_cycle_log_timeout(self):
        """wait_for_cycle_log returns None on timeout."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('visitor-1')
        result = await hb.wait_for_cycle_log('visitor-1', timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_cycle_log_unknown_subscriber(self):
        """wait_for_cycle_log returns None for unknown subscriber."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        result = await hb.wait_for_cycle_log('nobody', timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_emit_stage_to_bus(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb._bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('cortex', {'tokens': 100})
        msg = q.get_nowait()
        assert msg['stage'] == 'cortex'
        assert msg['data'] == {'tokens': 100}

    @pytest.mark.asyncio
    async def test_emit_stage_callback_and_bus_coexist(self):
        from heartbeat import Heartbeat
        hb = Heartbeat()
        legacy_calls = []
        hb.set_stage_callback(AsyncMock(side_effect=lambda s, d: legacy_calls.append(s)))
        q = hb._bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('body', {'action': 'sip_tea'})
        # Both paths got the message
        assert 'body' in legacy_calls
        assert not q.empty()

    @pytest.mark.asyncio
    async def test_emit_stage_callback_failure_does_not_block_bus(self):
        """Callback raising does not prevent bus publish."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.set_stage_callback(AsyncMock(side_effect=RuntimeError("boom")))
        q = hb._bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        await hb._emit_stage('cortex', {'x': 1})
        # Bus still got the message
        msg = q.get_nowait()
        assert msg['stage'] == 'cortex'

    @pytest.mark.asyncio
    async def test_emit_stage_bus_failure_does_not_break_cycle(self):
        """Bus exception in _emit_stage is caught (fail-open)."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        # Monkey-patch publish to raise
        hb._bus.publish = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bus-fail"))
        # Should not raise
        await hb._emit_stage('test', {})


# ---------------------------------------------------------------------------
# TestSceneUpdateIntegration
# ---------------------------------------------------------------------------

class TestSceneUpdateIntegration:
    def test_scene_update_topic_constant(self):
        """TOPIC_SCENE_UPDATE has expected value."""
        assert TOPIC_SCENE_UPDATE == 'outbound.scene_update'

    @pytest.mark.asyncio
    async def test_scene_update_bus_publish(self):
        """Verify bus.publish works for scene_update topic."""
        bus = EventBus()
        q = bus.subscribe(TOPIC_SCENE_UPDATE, 'viewer')
        broadcast_msg = {'type': 'scene_update', 'expression': 'neutral'}
        bus.publish(TOPIC_SCENE_UPDATE, broadcast_msg)
        assert q.get_nowait() == broadcast_msg

    @pytest.mark.asyncio
    async def test_scene_update_bus_exception_is_caught(self):
        """Bus failure in scene_update path must not propagate."""
        bus = EventBus()
        # Monkey-patch publish to raise
        original_publish = bus.publish
        def failing_publish(topic, msg):
            if topic == TOPIC_SCENE_UPDATE:
                raise RuntimeError("bus-fail")
            return original_publish(topic, msg)
        bus.publish = failing_publish

        # Simulate the fail-open pattern from heartbeat.py
        broadcast_msg = {'type': 'scene_update'}
        try:
            bus.publish(TOPIC_SCENE_UPDATE, broadcast_msg)
        except Exception:
            pass  # This is what the try/except in heartbeat.py does

        # Other topics still work
        q = bus.subscribe(TOPIC_STAGE_PROGRESS, 'test')
        bus.publish(TOPIC_STAGE_PROGRESS, {'stage': 'ok'})
        assert q.get_nowait() == {'stage': 'ok'}


# ---------------------------------------------------------------------------
# TestBusMessageFlow (TASK-117 integration tests)
# ---------------------------------------------------------------------------

class TestBusMessageFlow:
    """End-to-end bus message flow tests."""

    @pytest.mark.asyncio
    async def test_subscribe_publish_wait_roundtrip(self):
        """Full subscribe -> publish -> wait cycle via Heartbeat."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('alice')
        log = {'visitor_id': 'alice', 'dialogue': 'Hello!'}
        await hb._publish_cycle_log(log)
        result = await hb.wait_for_cycle_log('alice', timeout=1.0)
        assert result == log
        assert result['dialogue'] == 'Hello!'
        hb.unsubscribe_cycle_logs('alice')

    @pytest.mark.asyncio
    async def test_multiple_subscribers_independent(self):
        """Two subscribers get their own messages, not each other's."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('alice')
        hb.subscribe_cycle_logs('bob')

        log_alice = {'visitor_id': 'alice', 'dialogue': 'Hi from Alice'}
        log_bob = {'visitor_id': 'bob', 'dialogue': 'Hi from Bob'}

        await hb._publish_cycle_log(log_alice)
        await hb._publish_cycle_log(log_bob)

        result_alice = await hb.wait_for_cycle_log('alice', timeout=1.0)
        result_bob = await hb.wait_for_cycle_log('bob', timeout=1.0)

        assert result_alice['dialogue'] == 'Hi from Alice'
        assert result_bob['dialogue'] == 'Hi from Bob'

        hb.unsubscribe_cycle_logs('alice')
        hb.unsubscribe_cycle_logs('bob')

    @pytest.mark.asyncio
    async def test_wildcard_cycle_delivery(self):
        """Wildcard subscriber receives cycle logs from all visitors."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q_all = hb._bus.subscribe_keyed(TOPIC_CYCLE_COMPLETE, '*', 'watcher')

        hb.subscribe_cycle_logs('alice')
        hb.subscribe_cycle_logs('bob')

        log_alice = {'visitor_id': 'alice', 'data': 1}
        log_bob = {'visitor_id': 'bob', 'data': 2}
        log_ambient = {'type': 'idle'}  # no visitor_id -> key='*'

        await hb._publish_cycle_log(log_alice)
        await hb._publish_cycle_log(log_bob)
        await hb._publish_cycle_log(log_ambient)

        # Wildcard subscriber got all three
        msgs = []
        while not q_all.empty():
            msgs.append(q_all.get_nowait())
        assert len(msgs) == 3

        # Alice only got hers
        result_alice = await hb.wait_for_cycle_log('alice', timeout=0.1)
        assert result_alice['visitor_id'] == 'alice'

        # Bob only got his
        result_bob = await hb.wait_for_cycle_log('bob', timeout=0.1)
        assert result_bob['visitor_id'] == 'bob'

        hb.unsubscribe_cycle_logs('alice')
        hb.unsubscribe_cycle_logs('bob')

    @pytest.mark.asyncio
    async def test_concurrent_visitor_lock_serialization(self):
        """Two concurrent requests for the same visitor are serialized by lock."""
        bus = EventBus()
        lock = bus.visitor_lock('visitor-1')
        order = []
        results = []

        async def chat_handler(label, delay):
            async with lock:
                order.append(f'{label}-start')
                await asyncio.sleep(delay)
                results.append(f'response-{label}')
                order.append(f'{label}-end')

        t1 = asyncio.create_task(chat_handler('A', 0.05))
        await asyncio.sleep(0.01)
        t2 = asyncio.create_task(chat_handler('B', 0.01))
        await asyncio.gather(t1, t2)

        # A completes before B starts (serialized, not interleaved)
        assert order == ['A-start', 'A-end', 'B-start', 'B-end']
        # Both produced distinct responses
        assert len(results) == 2
        assert results[0] == 'response-A'
        assert results[1] == 'response-B'

    @pytest.mark.asyncio
    async def test_different_visitors_run_concurrently(self):
        """Two different visitors are NOT serialized -- they run in parallel."""
        bus = EventBus()
        lock_a = bus.visitor_lock('visitor-A')
        lock_b = bus.visitor_lock('visitor-B')
        order = []

        async def chat_handler(lock, label, delay):
            async with lock:
                order.append(f'{label}-start')
                await asyncio.sleep(delay)
                order.append(f'{label}-end')

        t1 = asyncio.create_task(chat_handler(lock_a, 'A', 0.05))
        await asyncio.sleep(0.01)
        t2 = asyncio.create_task(chat_handler(lock_b, 'B', 0.01))
        await asyncio.gather(t1, t2)

        # B starts before A ends (parallel, not serialized)
        assert order[0] == 'A-start'
        assert order[1] == 'B-start'
        assert 'B-end' in order
        assert 'A-end' in order

    @pytest.mark.asyncio
    async def test_scene_update_flows_through_bus(self):
        """Scene update published to bus is received by subscriber."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        q = hb._bus.subscribe(TOPIC_SCENE_UPDATE, 'window-viewer')
        msg = {'type': 'scene_update', 'expression': 'smile'}
        hb._bus.publish(TOPIC_SCENE_UPDATE, msg)
        result = await hb._bus.wait(q, timeout=1.0)
        assert result == msg

    @pytest.mark.asyncio
    async def test_unsubscribe_is_clean(self):
        """After unsubscribe, no stale references remain."""
        from heartbeat import Heartbeat
        hb = Heartbeat()
        hb.subscribe_cycle_logs('temp')
        assert 'temp' in hb._cycle_log_queues
        hb.unsubscribe_cycle_logs('temp')
        assert 'temp' not in hb._cycle_log_queues
        # Publishing after unsubscribe doesn't crash
        await hb._publish_cycle_log({'visitor_id': 'temp', 'x': 1})


# ---------------------------------------------------------------------------
# TestRequestContext (TASK-117)
# ---------------------------------------------------------------------------

class TestRequestContext:
    def test_heartbeat_property(self):
        from api.request_context import RequestContext

        class FakeServer:
            def __init__(self):
                self.heartbeat = 'hb-sentinel'
                self._bus = 'bus-sentinel'
        ctx = RequestContext(FakeServer())
        assert ctx.heartbeat == 'hb-sentinel'

    def test_bus_property(self):
        from api.request_context import RequestContext

        class FakeServer:
            def __init__(self):
                self.heartbeat = None
                self._bus = EventBus()
        ctx = RequestContext(FakeServer())
        assert isinstance(ctx.bus, EventBus)

    @pytest.mark.asyncio
    async def test_http_json_delegates(self):
        from api.request_context import RequestContext

        class FakeServer:
            def __init__(self):
                self.heartbeat = None
                self._bus = None
                self.calls = []
            async def _http_json(self, writer, status, body):
                self.calls.append((writer, status, body))

        server = FakeServer()
        ctx = RequestContext(server)
        await ctx.http_json('writer', 200, {'ok': True})
        assert server.calls == [('writer', 200, {'ok': True})]

    def test_server_escape_hatch(self):
        from api.request_context import RequestContext

        class FakeServer:
            def __init__(self):
                self.heartbeat = None
                self._bus = None
        server = FakeServer()
        ctx = RequestContext(server)
        assert ctx.server is server
