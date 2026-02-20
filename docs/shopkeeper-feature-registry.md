# The Shopkeeper — Feature Registry

Last updated: 2026-02-12

## Document Index

| Document | Purpose | Location |
|---|---|---|
| character-bible.md | Her soul — personality, voice, boundaries | /alive/docs/ |
| shopkeeper-v14-blueprint.md | Architecture spec — pipeline, drives, memory | /alive/docs/ |
| claude-code-prompt.md | Original build instructions | /alive/docs/ |
| claude-code-prompt-v2.md | Bug fixes + 4 features (server split, silence, end_engagement, drop) | /alive/docs/ |
| shopkeeper-art-guide.md | Visual design — 20 images, prompts, compositing | /alive/docs/ |
| mirror-feature-prompt.md | Mirror object + mirror_look function spec | /alive/docs/ |
| ALIVE_Sovereign_AI_Agents_Proposal.docx | Business proposal — 4-layer architecture | /alive/docs/ |

---

## Feature Status

### Core Architecture (v1.4)

| Feature | Status | Notes |
|---|---|---|
| Event-sourced system | ✅ Built | Append-only event log |
| Single Cortex call | ✅ Built | One LLM call per cycle |
| Homeostatic drives | ✅ Built + Fixed | Social, energy, curiosity, expression, rest |
| Weighted totems | ✅ Built + Fixed | Scoped by visitor_id |
| Stratified traits | ✅ Built | Contradiction detection |
| Disclosure gate | ✅ Built | Bans assistant tropes |
| Entropy manager | ✅ Built | Tracks repetition |
| Hand state physics | ✅ Built | Blocks hands-required actions |
| Subconscious stream | ✅ Built | Color-coded terminal MRI |

### Bug Fixes (3 Codex review rounds)

| Bug | Status | Round |
|---|---|---|
| Double visitor count | ✅ Fixed | Round 1 |
| should_process ignored | ✅ Fixed | Round 1 |
| Totem update scope | ✅ Fixed | Round 1 |
| Trait stability wrong order | ✅ Fixed | Round 1 |
| Blocking URL fetch in async | ✅ Fixed | Round 1 |
| place_item no executor handler | ✅ Fixed | Round 1 |
| Heartbeat not cancelled on shutdown | ✅ Fixed | Round 1 |
| Heartbeat not autonomous | ✅ Fixed | Round 2 |
| rest_need never increases | ✅ Fixed | Round 2 |
| Expression feedback loop broken | ✅ Fixed | Round 2 |
| SSRF on URL fetch | ✅ Fixed | Round 2 |
| UTC vs JST day boundary | ✅ Fixed | Round 2 |
| Gift metadata wrong message | ✅ Fixed | Round 2 |
| Empty kwargs SQL error | ✅ Fixed | Round 2 |
| Sleep cycle not scheduled | ✅ Fixed | Round 3 |
| Two-tier cadence (ambient vs creative) | ✅ Fixed | Round 3 |
| Engaged microcycles not periodic | ✅ Fixed | Round 3 |
| Self-state amnesia (cycle-to-cycle) | ✅ Fixed | Post-review |
| Ambient actions not in self_state | ✅ Fixed | Post-review |
| No physical self-description | ✅ Fixed | Post-review |
| Social 0.0 doesn't force end_engagement | ✅ Fixed | Post-review |
| write_journal during conversation | ✅ Fixed | Pre-review |
| ACK not instant | ✅ Fixed | Pre-review |
| "yo" classified as ambient | ✅ Fixed | Pre-review |

### Features — Shipped

| Feature | Status | Spec |
|---|---|---|
| End engagement | ✅ Built | She can end conversations (tired/boundary/natural) |
| Silence awareness | ✅ Built | Ambient cycles during visitor silence, 30-90s |
| Server/client split | ✅ Built | heartbeat_server.py + terminal.py via socket |
| Drop command | ✅ Built | drop URL, drop text, drop-file batch |
| Self-state block | ✅ Built | Last cycle's body/gaze/expression/thought fed back |

### Features — Specced, Not Built

| Feature | Spec | Priority |
|---|---|---|
| Mirror object | mirror-feature-prompt.md | P2 — after VPS deploy |
| Mirror look function | mirror-feature-prompt.md | P2 — needs image API |
| VPS deployment | Dockerfile + docker-compose | P1 — this week |
| Web UI | Next.js + WebSocket | P1 — next week |
| Character illustrations | shopkeeper-art-guide.md | P1 — start generating now |

### Features — Designed, Not Specced

| Feature | Description | Timeline |
|---|---|---|
| Discovery pipeline | She browses internet when curious | Month 2 |
| X feed reading | She reads her timeline/mentions | Month 2 |
| X posting (live) | She posts to X autonomously | Month 2 |
| JCOP4 wallet integration | Hardware-secured signing | Month 2-3 |
| ERC-8004 identity | On-chain agent registration | Month 3 |
| Observational memory upgrade | Mastra-style Observer/Reflector | Month 2 |
| Working memory (remember field) | Active memory writes mid-conversation | Month 2 |
| Semantic memory (vectors) | DuckDB embedded similarity search | Month 3+ |
| Character creation platform | Users birth their own characters | Month 4+ |
| Physical device ($68 kit) | Pi + LCD + JCOP4 + NFC | Month 6+ |
| iPad app | Client window into her life | Month 4+ |
| Mirror gallery browser | She reviews her past self-portraits | Month 3 |

---

## Architecture Decisions Log

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| LLM calls per cycle | 1 (Cortex only) | 2 (Router + Mind) | Cost, latency, determinism |
| Database | SQLite | Postgres, Vector DB | Portable, single file, sovereignty |
| Framework | None (raw asyncio) | Nanobot, LangChain | Anti-service philosophy conflict |
| Memory format | Text observations | JSON structures | Mastra research validates text > structured |
| Heartbeat model | Always-on background process | Request-driven | "She lives whether you visit or not" |
| Terminal delay | Stream-as-delay | Artificial 3-15s wait | Subconscious stream provides natural pacing |
| Device inference | Cloud API now, local later | Local-only | Quality too low on edge hardware today |
| Character ownership | Local SQLite + on-chain hash | Cloud-hosted | Users own their characters |
| Art style | AI-generated MVP, commission later | Commission first | Ship fast, upgrade later |
| Mirror | Object + function, not tool | Always-available tool | Must be gifted first, character milestone |

---

## Key Files

```
alive/
├── heartbeat_server.py      ← Her life (runs forever)
├── terminal.py              ← Visitor window (connects via socket)
├── db.py                    ← SQLite operations
├── seed.py                  ← Initial collection, journal, totems
├── sleep.py                 ← Daily consolidation (03:00-06:00 JST)
├── models/
│   ├── event.py             ← Event dataclass
│   └── state.py             ← Drives, Engagement, Visitor, Totem
├── config/
│   └── identity.py          ← Identity compact + voice checksum
├── pipeline/
│   ├── ack.py               ← Instant body response
│   ├── sensorium.py         ← Events → Perceptions
│   ├── gates.py             ← Strip internals, make diegetic
│   ├── affect.py            ← Subjective time coloring
│   ├── hypothalamus.py      ← Drives math
│   ├── thalamus.py          ← Routing + token budget
│   ├── hippocampus.py       ← Memory recall
│   ├── cortex.py            ← THE ONE LLM CALL
│   ├── validator.py         ← Schema + physics + disclosure + entropy
│   ├── executor.py          ← Emit events, update state
│   ├── hippocampus_write.py ← Memory writes, contradiction detection
│   ├── enrich.py            ← URL metadata fetching
│   └── mirror.py            ← Mirror image generation (placeholder)
└── data/
    ├── shopkeeper.db        ← Her mind
    └── mirrors/             ← Self-portrait gallery
```
