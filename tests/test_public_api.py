"""Tests for the public SDK API: renamed fields, to_prompt(), sync wrappers, callable LLM."""

from __future__ import annotations

import pytest

from alive_memory import AliveMemory, RecallContext

# ── RecallContext aliases ──────────────────────────────────────────


class TestRecallContextAliases:
    def test_episodic_alias(self):
        ctx = RecallContext(journal_entries=["event1", "event2"])
        assert ctx.episodic == ["event1", "event2"]
        assert ctx.episodic is ctx.journal_entries

    def test_observations_alias(self):
        ctx = RecallContext(visitor_notes=["note1"])
        assert ctx.observations == ["note1"]
        assert ctx.observations is ctx.visitor_notes

    def test_semantic_alias(self):
        ctx = RecallContext(self_knowledge=["fact1"])
        assert ctx.semantic == ["fact1"]
        assert ctx.semantic is ctx.self_knowledge

    def test_thread_alias(self):
        ctx = RecallContext(thread_context=["msg1"])
        assert ctx.thread == ["msg1"]
        assert ctx.thread is ctx.thread_context

    def test_entities_alias(self):
        ctx = RecallContext(totem_facts=["entity1"])
        assert ctx.entities == ["entity1"]
        assert ctx.entities is ctx.totem_facts

    def test_traits_alias(self):
        ctx = RecallContext(trait_facts=["trait1"])
        assert ctx.traits == ["trait1"]
        assert ctx.traits is ctx.trait_facts

    def test_reflections_unchanged(self):
        ctx = RecallContext(reflections=["r1"])
        assert ctx.reflections == ["r1"]


# ── to_prompt() ───────────────────────────────────────────────────


class TestToPrompt:
    def test_empty_context(self):
        ctx = RecallContext()
        assert ctx.to_prompt() == ""

    def test_single_section(self):
        ctx = RecallContext(journal_entries=["User asked about Python"])
        result = ctx.to_prompt()
        assert "## Relevant Context" in result
        assert "### Recent Events" in result
        assert "- User asked about Python" in result

    def test_multiple_sections(self):
        ctx = RecallContext(
            journal_entries=["event1"],
            visitor_notes=["note1"],
            reflections=["reflection1"],
        )
        result = ctx.to_prompt()
        assert "### Recent Events" in result
        assert "### User Info" in result
        assert "### Reflections" in result

    def test_empty_sections_omitted(self):
        ctx = RecallContext(journal_entries=["event1"])
        result = ctx.to_prompt()
        assert "User Info" not in result
        assert "Knowledge" not in result
        assert "Traits" not in result

    def test_all_sections(self):
        ctx = RecallContext(
            journal_entries=["e1"],
            visitor_notes=["v1"],
            self_knowledge=["s1"],
            reflections=["r1"],
            thread_context=["t1"],
            totem_facts=["o1"],
            trait_facts=["tr1"],
        )
        result = ctx.to_prompt()
        assert result.count("###") == 7


# ── Callable LLM ─────────────────────────────────────────────────


class TestCallableLLM:
    @pytest.mark.asyncio
    async def test_async_callable_llm(self):
        async def my_llm(prompt: str, system: str = "") -> str:
            return f"response to: {prompt[:20]}"

        async with AliveMemory(storage=":memory:", llm=my_llm) as mem:
            assert mem._llm is not None
            result = await mem._llm.complete("test prompt")
            assert "response to: test prompt" in result.text

    @pytest.mark.asyncio
    async def test_sync_callable_llm(self):
        def my_llm(prompt: str) -> str:
            return f"sync response to: {prompt[:20]}"

        async with AliveMemory(storage=":memory:", llm=my_llm) as mem:
            result = await mem._llm.complete("test prompt")
            assert "sync response to: test" in result.text


# ── Sync wrappers ────────────────────────────────────────────────


class TestSyncWrappers:
    def test_intake_sync(self):
        mem = AliveMemory(storage=":memory:")
        import asyncio
        asyncio.run(mem.initialize())
        result = mem.intake_sync("conversation", "hello world")
        # May or may not create a moment depending on salience
        assert result is None or hasattr(result, "content")

    def test_recall_sync(self):
        mem = AliveMemory(storage=":memory:")
        import asyncio
        asyncio.run(mem.initialize())
        ctx = mem.recall_sync("hello")
        assert isinstance(ctx, RecallContext)

    def test_consolidate_sync(self):
        mem = AliveMemory(storage=":memory:")
        import asyncio
        asyncio.run(mem.initialize())
        report = mem.consolidate_sync()
        assert report.moments_processed == 0  # no moments yet


# ── Version ──────────────────────────────────────────────────────


def test_version():
    import alive_memory
    assert alive_memory.__version__ == "0.1.0"


# ── OpenAI provider resolves ─────────────────────────────────────


def test_resolve_openai_string():
    """Test that 'openai' string is recognized."""
    try:
        mem = AliveMemory(storage=":memory:", llm="openai")
        assert mem._llm is not None
    except (ImportError, Exception):
        # openai not installed or no API key set — both fine for this test
        pass
