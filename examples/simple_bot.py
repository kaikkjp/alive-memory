"""Simple example: intake → recall → consolidate cycle.

Run with:
    python examples/simple_bot.py
"""

import asyncio
from alive_memory import AliveMemory


async def main():
    async with AliveMemory(
        storage="example.db",
        memory_dir="example_memory",
    ) as memory:

        # 1. Record some events
        print("Recording events...")

        m1 = await memory.intake(
            "conversation",
            "The visitor asked about the old temple on the hill.",
            metadata={"salience": 0.9, "visitor_name": "Alice"},
        )
        print(f"  Moment 1: {'recorded' if m1 else 'below threshold'}")

        m2 = await memory.intake(
            "observation",
            "A cat wandered into the shop and curled up by the window.",
            metadata={"salience": 0.8},
        )
        print(f"  Moment 2: {'recorded' if m2 else 'below threshold'}")

        m3 = await memory.intake(
            "system",
            "ok",  # Too short / low-info — should be gated out
        )
        print(f"  Moment 3: {'recorded' if m3 else 'below threshold (expected)'}")

        # 2. Consolidate (sleep) — processes moments into hot memory
        print("\nConsolidating (no LLM — raw journal writes)...")
        report = await memory.consolidate()
        print(f"  Processed: {report.moments_processed} moments")
        print(f"  Journal entries: {report.journal_entries_written}")
        print(f"  Cold embeddings: {report.cold_embeddings_added}")

        # 3. Recall from hot memory
        print("\nRecalling 'temple'...")
        ctx = await memory.recall("temple", limit=5)
        print(f"  Total hits: {ctx.total_hits}")
        for entry in ctx.journal_entries:
            print(f"  Journal: {entry[:80]}...")

        # 4. Check cognitive state
        state = await memory.get_state()
        print(f"\nCognitive state:")
        print(f"  Mood: {state.mood.word} (valence={state.mood.valence:.2f})")
        print(f"  Drives: curiosity={state.drives.curiosity:.2f}, social={state.drives.social:.2f}")

        # 5. Inject backstory
        bs = await memory.inject_backstory(
            "I am a shopkeeper in a quiet town. My shop sells curiosities.",
            title="identity",
        )
        print(f"\nBackstory injected: {bs.content[:50]}...")

    # Cleanup
    import os, shutil
    os.unlink("example.db")
    shutil.rmtree("example_memory", ignore_errors=True)
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
