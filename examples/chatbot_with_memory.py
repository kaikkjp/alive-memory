"""Chatbot with memory — shows intake, recall, and consolidation with an LLM.

Requires:
    pip install alive-memory[anthropic]
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python examples/chatbot_with_memory.py
"""

import asyncio

from alive_memory import AliveMemory


async def main():
    async with AliveMemory(
        storage="chatbot.db",
        memory_dir="chatbot_memory",
        llm="anthropic",  # reads ANTHROPIC_API_KEY from env
    ) as memory:

        # Simulate a conversation
        messages = [
            ("conversation", "User asked: What's your favorite season?"),
            ("conversation", "I told them I love autumn — the colors remind me of old paintings."),
            ("conversation", "User shared that they're moving to a new city next month."),
            ("observation", "The conversation felt warm and genuine today."),
        ]

        print("=== Recording conversation ===")
        for event_type, content in messages:
            moment = await memory.intake(event_type, content)
            status = f"recorded (salience={moment.salience:.2f})" if moment else "below threshold"
            print(f"  [{event_type}] {status}")

        # Consolidate — LLM reflects on the moments, writes journal
        print("\n=== Consolidating (sleep) ===")
        report = await memory.consolidate()
        print(f"  Moments processed: {report.moments_processed}")
        print(f"  Journal entries: {report.journal_entries_written}")
        print(f"  Dreams: {len(report.dreams)}")

        for i, dream in enumerate(report.dreams, 1):
            print(f"  Dream {i}: {dream[:80]}...")

        # Recall
        print("\n=== Recalling 'autumn' ===")
        ctx = await memory.recall("autumn", limit=3)
        print(f"  Hits: {ctx.total_hits}")
        for entry in ctx.journal_entries[:3]:
            print(f"  Journal: {entry[:100]}...")

        # Check state
        state = await memory.get_state()
        print("\n=== Cognitive state ===")
        print(f"  Mood: {state.mood.word} (valence={state.mood.valence:.2f})")
        print(f"  Energy: {state.energy:.2f}")

    # Cleanup
    import os
    import shutil
    os.unlink("chatbot.db")
    shutil.rmtree("chatbot_memory", ignore_errors=True)
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
