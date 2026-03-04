---
name: alive-memory
description: "Cognitive memory layer — remember conversations with emotional valence, drive coupling, consolidation, and identity drift."
user-invocable: true
metadata: {"openclaw": {"emoji": "🧠", "requires": {"bins": ["curl"], "env": ["ALIVE_MEMORY_URL"]}, "primaryEnv": "ALIVE_MEMORY_API_KEY"}}
---

# alive-memory — Cognitive Memory

You have access to a cognitive memory system. Use it to remember important things from conversations, recall relevant context before responding, and maintain a persistent identity across sessions.

**Always** recall relevant memories before responding to a user message. **Always** store important new information after a meaningful exchange.

## Environment

- `ALIVE_MEMORY_URL` — Base URL of the alive-memory server (e.g. `http://localhost:8100`)
- `ALIVE_MEMORY_API_KEY` — Optional bearer token for authentication

If `ALIVE_MEMORY_API_KEY` is set, include `-H "Authorization: Bearer $ALIVE_MEMORY_API_KEY"` in all requests except health.

## When to Store Memories

Store a memory via `/intake` when:
- The user shares personal information (name, preferences, facts about themselves)
- An important decision is made
- The user asks you to remember something
- A meaningful conversation exchange occurs
- You observe something noteworthy

Do NOT store trivial messages like "ok", "thanks", greetings, or small talk.

## When to Recall

Recall memories via `/recall` when:
- Before responding to any substantive user message (use the message as the query)
- The user asks "do you remember..." or references past conversations
- You need context about the user's preferences or history

Include recalled memories as context when forming your response. Do not dump raw memory data to the user — integrate it naturally.

## API Reference

### Store a Memory

```bash
curl -s -X POST "$ALIVE_MEMORY_URL/intake" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY" \
  -d '{
    "event_type": "conversation",
    "content": "The user said their favorite color is blue",
    "metadata": {"topic": "preferences"}
  }'
```

Event types: `conversation`, `observation`, `action`, `system`

### Recall Memories

```bash
curl -s -X POST "$ALIVE_MEMORY_URL/recall" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY" \
  -d '{"query": "user preferences", "limit": 5}'
```

Returns a `RecallContextResponse` with categorized results from hot memory (journal entries, visitor notes, self-knowledge, reflections). Results are ranked by keyword relevance with mood-congruent and drive-coupled re-ranking.

### Check Cognitive State

```bash
curl -s "$ALIVE_MEMORY_URL/state" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY"
```

Returns mood (valence, arousal, word), drives (curiosity, social, expression, rest), energy, and cycle count. Use this to understand your current emotional and motivational state.

### Check Identity

```bash
curl -s "$ALIVE_MEMORY_URL/identity" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY"
```

Returns your self-model: personality traits, behavioral summary, and drift history.

### Inject Backstory

```bash
curl -s -X POST "$ALIVE_MEMORY_URL/backstory" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY" \
  -d '{"content": "I was created to be a helpful companion.", "title": "origin"}'
```

Creates a high-strength semantic memory. Use for foundational knowledge about yourself.

### Adjust Drives

```bash
curl -s -X POST "$ALIVE_MEMORY_URL/drives/curiosity" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY" \
  -d '{"delta": 0.1}'
```

Drive names: `curiosity`, `social`, `expression`, `rest`. Delta range: -1.0 to 1.0.

### Consolidate (Sleep)

```bash
curl -s -X POST "$ALIVE_MEMORY_URL/consolidate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ALIVE_MEMORY_API_KEY" \
  -d '{"depth": "nap"}'
```

Run periodically to process day moments into journal entries, generate reflections, embed to cold archive, and optionally dream. Use `"full"` for complete consolidation (requires LLM on the server side) or `"nap"` for light processing.

### Health Check

```bash
curl -s "$ALIVE_MEMORY_URL/health"
```

No auth required. Returns `{"status": "ok", "version": "..."}`.

## Typical Flow

1. User sends a message
2. **Recall** memories relevant to the message
3. Use recalled context to inform your response
4. **Store** any new important information from the exchange
5. Respond to the user

## Tips

- Write memory content as factual summaries, not raw quotes. Instead of storing `"User: my dog's name is Rex"`, store `"The user's dog is named Rex"`.
- Include topic metadata when storing: `{"topic": "pets"}`, `{"topic": "work"}`, etc.
- Check `/state` occasionally to be aware of your mood and drives.
- Run `/consolidate` with `"depth": "nap"` at natural conversation breaks.
