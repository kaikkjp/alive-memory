"""Full sleep cycle — shows the complete sleep orchestrator.

Demonstrates: intake → accumulate → sleep (whisper + consolidate + meta + identity + wake).

Requires:
    pip install alive-memory[anthropic]
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python examples/sleep_cycle.py
"""

import asyncio

from alive_memory import AliveMemory, SleepConfig


async def main():
    async with AliveMemory(
        storage="agent.db",
        memory_dir="agent_memory",
        llm="anthropic",
    ) as memory:

        # Inject a backstory so the agent has an identity
        print("=== Injecting backstory ===")
        await memory.inject_backstory(
            "I am a curious researcher who studies patterns in nature. "
            "I value deep conversation and careful observation.",
            title="identity",
        )

        # Simulate a day of events
        print("\n=== Simulating a day ===")
        events = [
            ("conversation", "A student asked about fractal patterns in ferns."),
            ("observation", "I noticed the library was unusually quiet today."),
            ("conversation", "Colleague shared a paper on collective memory in ant colonies."),
            ("action", "I spent an hour sketching branching patterns."),
            ("conversation", "A visitor asked if memories can evolve over time."),
            ("observation", "The sunset had an unusual orange hue this evening."),
        ]

        for event_type, content in events:
            moment = await memory.intake(event_type, content)
            if moment:
                print(f"  Recorded: {content[:60]}... (salience={moment.salience:.2f})")

        # Run the full sleep cycle
        print("\n=== Running sleep cycle ===")
        report = await memory.sleep(
            sleep_config=SleepConfig(
                enable_meta_review=False,      # no drive provider in this example
                enable_meta_controller=False,   # no metrics provider
                enable_wake=False,              # no wake hooks
            ),
        )

        print(f"  Depth: {report.depth}")
        print(f"  Moments consolidated: {report.moments_consolidated}")
        print(f"  Journal entries: {report.journal_entries_written}")
        print(f"  Dreams: {report.dreams_generated}")
        print(f"  Drift detected: {report.drift_detected}")
        print(f"  Phases completed: {', '.join(report.phases_completed)}")
        print(f"  Duration: {report.duration_seconds:.2f}s")

        if report.errors:
            print(f"  Errors: {report.errors}")

        # Check identity after sleep
        identity = await memory.get_identity()
        print("\n=== Identity ===")
        print(f"  Traits: {identity.traits}")

    # Cleanup
    import os
    import shutil
    os.unlink("agent.db")
    shutil.rmtree("agent_memory", ignore_errors=True)
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
