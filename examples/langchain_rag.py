"""LangChain RAG integration — use alive-memory as a retriever in a chain.

Requires:
    pip install alive-memory[anthropic,langchain]
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python examples/langchain_rag.py
"""

import asyncio

from alive_memory import AliveMemory


async def main():
    async with AliveMemory(
        storage="rag_demo.db",
        memory_dir="rag_memory",
        llm="anthropic",
    ) as memory:

        # Seed some memories
        print("=== Seeding memories ===")
        facts = [
            ("conversation", "The capital of France is Paris."),
            ("conversation", "Python was created by Guido van Rossum in 1991."),
            ("conversation", "The speed of light is approximately 299,792 km/s."),
            ("observation", "User seems very interested in science topics."),
            ("conversation", "Mars has two moons: Phobos and Deimos."),
        ]
        for event_type, content in facts:
            await memory.intake(event_type, content)

        # Consolidate so entries land in hot memory
        await memory.consolidate()
        print("  Consolidated.")

        # Use the LangChain retriever
        from alive_memory.adapters.langchain import AliveRetriever

        retriever = AliveRetriever(memory=memory, recall_limit=3)

        # Retrieve relevant documents
        print("\n=== Retrieving 'Mars moons' ===")
        docs = await retriever.ainvoke("Mars moons")
        for doc in docs:
            print(f"  [{doc.metadata.get('category', '?')}] {doc.page_content[:100]}")

        print("\n=== Retrieving 'Python programming' ===")
        docs = await retriever.ainvoke("Python programming")
        for doc in docs:
            print(f"  [{doc.metadata.get('category', '?')}] {doc.page_content[:100]}")

        if not docs:
            print("  (no matches — try broader keywords)")

        # Use as chat message history
        from alive_memory.adapters.langchain import AliveMessageHistory

        from langchain_core.messages import AIMessage, HumanMessage

        history = AliveMessageHistory(memory=memory)
        await history.aadd_messages([
            HumanMessage(content="Tell me about Mars"),
            AIMessage(content="Mars is the fourth planet from the Sun..."),
        ])

        messages = await history.aget_messages()
        print(f"\n=== Chat history: {len(messages)} messages ===")
        for msg in messages:
            print(f"  {msg.type}: {msg.content[:60]}...")

    # Cleanup
    import os
    import shutil
    os.unlink("rag_demo.db")
    shutil.rmtree("rag_memory", ignore_errors=True)
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
