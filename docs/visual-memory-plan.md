# Visual Memory Plan

## Summary

Extend alive-memory to search external visual databases alongside its own cold_memory. Visual content becomes part of the agent's inner life — recallable in conversation, surfaceable in dreams.

## Motivation

Agents that consume visual media (manga pages, images, videos) currently have no way to recall that content through alive-memory. Their reading experiences are stored as text summaries, but the actual visual source material — the panels, the art, the expressions — is inaccessible to recall and dreaming.

The first use case is Maru, an agent reading One Piece manga. She has a pre-built embedding database of 21,665 manga pages embedded with Gemini 2's multimodal embedder (3072 dimensions). These embeddings encode what the pages *look like*, not just text on them.

Without visual memory, Maru remembers chapters as text summaries: "Shanks lost his arm." With visual memory, she can flip back to the actual page showing that moment — and describe what she sees from the art itself.

## Architecture decision: reference, don't import

The visual embedding database is not copied into alive-memory's storage. Instead, alive-memory **registers external visual sources** and searches them at recall/dream time. The visual DB stays external, owned by whoever produced it.

```
cold_memory (alive-memory's DB)     ← OpenAI text embeddings, personal experience
visual_memory (external DB)          ← Gemini multimodal embeddings, source material
                ↘  ↙
          combined at recall time
```

### Why reference instead of import

- **No data duplication.** The manga page DB is ~260MB of embeddings. Copying it into alive-memory doubles storage for no benefit.
- **Separation of concerns.** The page DB is source material — it exists independently of the agent. Multiple agents could share the same visual source.
- **Producer independence.** The visual DB is populated by a separate pipeline (embedding script, reader, etc.). alive-memory is read-only on it.
- **Generality.** Any agent consuming any visual media can register a source with whatever schema their DB has. Not tied to manga or One Piece.

### Why not use the same embedder for everything

alive-memory's cold_memory uses OpenAI `text-embedding-3-small` (1536 dimensions). The manga pages use Gemini multimodal embeddings (3072 dimensions). These are in completely different vector spaces — cosine similarity between them is meaningless.

Options considered:
1. **Switch alive-memory to Gemini's embedder** — would work for Maru but forces a Google dependency on all alive-memory users. Bad for a general library.
2. **Re-embed pages with OpenAI text embedder** — loses visual understanding. The embeddings would encode filenames, not panel content.
3. **Keep them separate, search in parallel** — each store uses its own embedder. Combined at recall time. No compromises.

Option 3 is the right call.

## Embedding compatibility

The key constraint: to search visual embeddings, the query must be embedded with the **same model** that produced the stored embeddings. Gemini's multimodal embedder supports text-to-image queries natively — a text query "Shanks sacrifice" returns a vector in the same space as the image embeddings. So text queries work against image embeddings, but only within the Gemini embedding space.

This means alive-memory needs a `GeminiEmbedder` for visual queries, separate from its default OpenAI text embedder.

## Reading boundary

A critical constraint for agents that read sequentially: visual recall must be filtered by reading progress. Maru on chapter 10 must not recall pages from chapter 100. The `VisualSource` config specifies which column enforces this boundary (`max_boundary_col`), and the caller passes the current boundary value at search time.

## Changes to alive-memory

### 1. New concept: `VisualSource`

A dataclass describing an external visual DB:

```python
@dataclass
class VisualSource:
    path: str | Path           # path to the sqlite DB
    embedder: EmbeddingProvider # Gemini multimodal embedder for queries
    table: str = "pages"       # table name
    embedding_col: str = "embedding"
    content_col: str = "filepath"
    metadata_cols: list[str]   # e.g. ["chapter_num", "page_num"]
    max_boundary_col: str | None = None  # e.g. "chapter_num"
```

Generic enough for any visual media DB, not just manga.

**Files:** new `alive_memory/visual/__init__.py`

### 2. Visual search function

```python
async def search_visual(
    source: VisualSource,
    query: str,
    *,
    limit: int = 5,
    boundary: int | None = None,
) -> list[VisualMatch]
```

- Embeds `query` with the source's Gemini embedder
- Reads stored embeddings from the external DB
- Cosine similarity, filtered by boundary
- Returns matches with metadata (chapter, page, filepath, score)

**Files:** new `alive_memory/visual/search.py`

### 3. Hook into recall (hippocampus.py)

After searching cold_memory, also search registered visual sources. Results go into a new field on `RecallContext`:

```python
@dataclass
class RecallContext:
    # existing fields...
    visual: list[VisualMatch] = field(default_factory=list)
```

**Files:** modify `alive_memory/recall/hippocampus.py`, modify `alive_memory/types.py`

### 4. Hook into dreaming (cold_search.py)

`find_cold_echoes()` searches cold_memory for related past content. Add a parallel search against visual sources. During dreaming, a moment about "Luffy's determination" could surface the chapter 1 page where he sets sail.

**Files:** modify `alive_memory/consolidation/cold_search.py`

### 5. AliveMemory init

Add `visual_sources` parameter:

```python
AliveMemory(
    storage="memory.db",
    llm="openrouter",
    visual_sources=[
        VisualSource(
            path="onepiece_kb.db",
            embedder=GeminiEmbedder(),
            metadata_cols=["chapter_num", "page_num"],
            max_boundary_col="chapter_num",
        )
    ],
)
```

**Files:** modify `alive_memory/__init__.py`

### 6. GeminiEmbedder

New embedding provider that calls Gemini's multimodal embedding API. Used only for visual source queries.

**Files:** new `alive_memory/embeddings/gemini.py`

## Changes to alive-window (Maru integration)

### 7. Wire visual source in server.py

When creating AliveMemory for Maru, register the onepiece_kb visual source with the reading boundary set to current chapter.

### 8. Prompt integration

When `RecallContext.visual` has matches, include page references in the cortex prompt. Optionally send top 1-2 pages through the vision LLM for Maru to "look at" before responding — describing the art, the panel composition, character expressions.

## What stays untouched

- `cold_memory` table and search
- `onepiece_kb.db` (read-only)
- `reader.py` and `maru.db`
- alive-memory's default embedder (OpenAI)
- Existing recall and dreaming behavior (additive only)

## Estimated scope

| Component | Files | Lines |
|-----------|-------|-------|
| `VisualSource` + search | 2 new | ~100 |
| `GeminiEmbedder` | 1 new | ~40 |
| Recall hook | 1 modified | ~20 |
| Dream hook | 1 modified | ~15 |
| AliveMemory init | 1 modified | ~10 |
| RecallContext type | 1 modified | ~5 |
| alive-window wiring | 2 modified | ~20 |
| **Total** | **~10 files** | **~210 lines** |

## Execution order

1. `GeminiEmbedder` — need this first to query
2. `VisualSource` + `search_visual()` — the core search function
3. Recall hook — makes it work in conversation
4. Dream hook — makes it part of her inner life
5. Wire into alive-window — connect it to Maru

## Future generalization

This design is not manga-specific. Any agent consuming visual media can use it:
- An art agent with embedded gallery images
- A video agent with embedded keyframes
- A photography agent with embedded photos

The `VisualSource` abstraction handles any SQLite DB with an embedding column and metadata columns. The only requirement is that the embeddings were produced by a model whose embedder is available for query-side embedding.
