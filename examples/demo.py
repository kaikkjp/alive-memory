"""alive-memory demo — 30 seconds to cognitive memory.

Run:
    pip install alive-memory
    python examples/demo.py
"""

import asyncio
import shutil
import tempfile

from alive_memory import AliveMemory


async def main():
    # Create a temporary directory so the demo is self-contained
    tmpdir = tempfile.mkdtemp(prefix="alive_demo_")

    print("=== alive-memory demo ===\n")

    async with AliveMemory(
        storage=f"{tmpdir}/demo.db",
        memory_dir=f"{tmpdir}/hot",
    ) as memory:

        # 1. Record some conversations
        events = [
            ("conversation", "User: What's the best way to learn Python?"),
            ("conversation", "Agent: Start with the official tutorial, then build projects."),
            ("conversation", "User: I'm building a CLI tool for task management."),
            ("conversation", "User: Can you help me with argparse?"),
            ("observation", "User seems interested in developer tooling and CLI apps."),
            ("conversation", "User: I also love cooking Italian food on weekends."),
        ]

        print("Recording events...")
        for event_type, content in events:
            moment = await memory.intake(event_type, content)
            status = f"  salience={moment.salience:.2f}" if moment else "  (below threshold)"
            print(f"  {content[:60]}...{status}")

        # 2. Recall relevant context
        print("\nRecalling 'Python CLI'...")
        context = await memory.recall("Python CLI")
        print(context.to_prompt() or "  (no matches yet — try after consolidation)")

        # 3. Consolidate (sleep)
        print("\nConsolidating memories...")
        report = await memory.consolidate(depth="nap")
        print(f"  Processed {report.moments_processed} moments")

        # 4. Recall again after consolidation
        print("\nRecalling 'Python' after consolidation...")
        context = await memory.recall("Python")
        prompt_text = context.to_prompt()
        if prompt_text:
            print(prompt_text)
        else:
            print("  (empty — salience gating filtered events)")

        # 5. Check cognitive state
        state = await memory.get_state()
        print("\nCognitive state:")
        print(f"  Mood: {state.mood.word} (valence={state.mood.valence:.2f})")
        print(f"  Drives: curiosity={state.drives.curiosity:.2f}, social={state.drives.social:.2f}")
        print(f"  Cycle: {state.cycle_count}")

    # Clean up
    shutil.rmtree(tmpdir)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
