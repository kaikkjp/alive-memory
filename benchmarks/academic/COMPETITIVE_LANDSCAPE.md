# Competitive Landscape: Long-Term Memory Systems

Benchmark scores collected March 2026 from published papers and official repos.

## Metric Warning

**Scores across papers are NOT directly comparable** unless they use the same
evaluation metric. The two dominant metrics are:

| Metric | Range | Used By |
|--------|-------|---------|
| **LLM-as-Judge** (binary 0/1) | 0–100 | Mnemis, MAGMA, EMem-G, Nemori, EverMemOS |
| **Token F1** | 0–100 | AriadneMem, original LoCoMo paper |

LLM-as-Judge scores are typically 2–3x higher than token F1 on the same
predictions because the judge accepts paraphrases and partial matches that
token overlap misses.

Our harness (`benchmarks/academic/harness/scoring.py`) supports both metrics.
Use `--judge-model` flag to enable LLM-as-Judge scoring alongside token F1.

---

## LoCoMo Benchmark

10 conversations, ~272 sessions, 1,986 QA pairs across 5 categories.
Category 5 (adversarial) is excluded from overall scores by convention.

### LLM-as-Judge Scores (binary 0/1, higher = better)

Source: Mnemis paper (arxiv 2602.15313), MAGMA paper (arxiv 2601.03236)

| System | Multi-Hop | Temporal | Open-Domain | Single-Hop | Overall | LLM |
|--------|:---------:|:--------:|:-----------:|:----------:|:-------:|-----|
| **Mnemis** (k=30) | 92.9 | 90.7 | 79.2 | 97.1 | **93.9** | GPT-4.1-mini |
| **Mnemis** | 91.8 | 90.3 | 82.3 | 96.2 | 93.3 | GPT-4.1-mini |
| EverMemOS | 91.1 | 89.7 | 70.8 | 96.1 | 92.3 | GPT-4.1-mini |
| Mnemis | 89.7 | 77.6 | 79.2 | 95.7 | 89.8 | GPT-4o-mini |
| EMem-G | 79.6 | 80.8 | 71.7 | 90.5 | 85.3 | GPT-4.1-mini |
| Full Context | 77.2 | 74.2 | 56.6 | 86.9 | 80.6 | GPT-4.1-mini |
| Nemori | 75.1 | 77.6 | 51.0 | 84.9 | 79.5 | GPT-4.1-mini |
| EMem-G | 74.7 | 76.0 | 57.3 | 82.3 | 78.0 | GPT-4o-mini |
| Nemori | 65.3 | 71.0 | 44.8 | 82.1 | 74.4 | GPT-4o-mini |
| RAG | 64.9 | 76.6 | 67.7 | 76.5 | 73.8 | GPT-4.1-mini |
| LangMem | 71.0 | 50.8 | 59.0 | 84.5 | 73.4 | GPT-4.1-mini |
| MemOS | 64.3 | 73.2 | 55.2 | 78.4 | 73.3 | GPT-4o-mini |
| MAGMA | 52.8 | 65.0 | 51.7 | 77.6 | 70.0 | GPT-4.1-mini |
| RAG | 59.9 | 62.9 | 63.5 | 73.5 | 68.2 | GPT-4o-mini |
| Full Context | 66.8 | 56.2 | 48.6 | 83.0 | 72.3 | GPT-4o-mini |
| Mem0 | 68.2 | 56.9 | 47.9 | 71.4 | 66.3 | GPT-4.1-mini |
| PREMem | 61.0 | 74.8 | 46.9 | 66.2 | 65.8 | GPT-4.1-mini |
| Mem0 | 60.3 | 50.4 | 40.6 | 68.1 | 61.3 | GPT-4o-mini |
| Zep | 53.7 | 60.2 | 43.8 | 66.9 | 61.6 | GPT-4.1-mini |
| Zep | 50.5 | 58.9 | 39.6 | 63.2 | 58.5 | GPT-4o-mini |

### Token F1 Scores

Source: AriadneMem paper (arxiv 2603.03290), MAGMA appendix

| System | Multi-Hop | Temporal | Open-Domain | Single-Hop | Overall | LLM |
|--------|:---------:|:--------:|:-----------:|:----------:|:-------:|-----|
| Nemori | 36.3 | 56.9 | 24.7 | 54.8 | 50.2 | GPT-4o-mini |
| AriadneMem | — | 64.3 | — | — | 46.3 | GPT-4.1-mini |
| AriadneMem | — | 57.9 | — | — | 42.6 | GPT-4o |
| MAGMA | 26.4 | 50.9 | 18.0 | 55.1 | 46.7 | GPT-4.1-mini |
| MemOS | 36.5 | 43.4 | 24.6 | 49.3 | 41.3 | GPT-4o-mini |
| Mem0 | — | 52.4 | — | — | 36.1 | GPT-4o |
| Full Context | 18.2 | 7.9 | 4.2 | 22.9 | 14.0 | GPT-4o-mini |

---

## LongMemEval-S Benchmark

500 questions, ~19k sessions, ~115k tokens per question haystack.
Categories: SSU (single-session-user), MS (multi-session), SSP (single-session-preference),
TR (temporal-reasoning), KU (knowledge-update), SSA (single-session-assistant).

### LLM-as-Judge Scores (binary 0/1)

Source: Mnemis paper (arxiv 2602.15313), MAGMA paper (arxiv 2601.03236)

| System | SSU | MS | SSP | TR | KU | SSA | Overall | LLM |
|--------|:---:|:--:|:---:|:--:|:--:|:---:|:-------:|-----|
| **Mnemis** | 98.6 | 86.5 | 100.0 | — | — | — | **91.6** | GPT-4.1-mini |
| Mnemis | 97.1 | 76.7 | 90.0 | 83.5 | 92.3 | 100.0 | 87.2 | GPT-4o-mini |
| EMem-G | 87.0 | 73.6 | 32.2 | 74.8 | 94.4 | 87.5 | 77.9 | GPT-4o-mini |
| RAG | 82.9 | 54.9 | 86.7 | 67.7 | 80.8 | 94.6 | 72.6 | GPT-4.1-mini |
| Mem0 | 91.4 | 66.2 | 34.0 | 63.9 | 74.4 | 96.4 | 71.1 | GPT-4o-mini |
| RAG | 88.6 | 47.4 | 70.0 | 63.2 | 70.5 | 91.1 | 67.2 | GPT-4o-mini |
| Full Context | 85.7 | 51.1 | 16.7 | 60.2 | 76.9 | 98.2 | 65.6 | GPT-4.1-mini |
| Nemori | 88.6 | 51.1 | 46.7 | 61.7 | 61.5 | 83.9 | 64.2 | GPT-4o-mini |
| Zep | 92.9 | 47.4 | 53.3 | 54.1 | 74.4 | 75.0 | 63.2 | GPT-4o-mini |
| MAGMA | 72.9 | 50.4 | 73.3 | 45.1 | 66.7 | 83.9 | 61.2 | GPT-4.1-mini |
| Full Context | 78.6 | 38.3 | 6.7 | 42.1 | 78.2 | 89.3 | 55.0 | GPT-4o-mini |

---

## System Architecture Summary

| System | Memory Type | Graph? | Temporal? | Open Source? |
|--------|------------|:------:|:---------:|:------------:|
| Mnemis | Hierarchical graph + dual-route retrieval | Yes | Yes | Yes (Microsoft) |
| EverMemOS | Self-organizing memory OS | Yes | Yes | Yes |
| MAGMA | Multi-graph (semantic/temporal/causal/entity) | Yes | Yes | Partial |
| AriadneMem | Offline graph + online reasoning | Yes | Yes | Yes |
| EMem-G | Episodic graph memory | Yes | Yes | Yes |
| Nemori | Graph-RAG | Yes | Yes | Yes |
| Mem0 | Extract/consolidate/retrieve + graph variant | Optional | No | Yes |
| Zep/Graphiti | Temporal knowledge graph | Yes | Yes | Yes |
| Letta/MemGPT | Hierarchical OS-inspired tiers | No | No | Yes |
| A-Mem | Zettelkasten-style linked notes | No | No | Yes |
| **alive-memory** | 3-tier (day/hot/cold) + salience gating | No | Yes | Yes |

---

## Key Observations

1. **Graph-based systems dominate**: Top performers (Mnemis, EverMemOS, EMem-G)
   all use structured graph representations rather than flat vector stores.

2. **Dual retrieval matters**: Mnemis's System-1 (similarity) + System-2 (global
   selection) approach achieves the highest scores, suggesting that similarity
   search alone is insufficient.

3. **Adversarial exclusion**: Most papers exclude Category 5 (adversarial) from
   LoCoMo overall scores. Our harness scores it separately.

4. **Metric inconsistency**: Token F1 scores are dramatically lower than
   LLM-as-Judge scores. Full Context gets 14.0 F1 vs 72.3 Judge on LoCoMo.
   Papers should always specify which metric they use.

5. **LLM backbone matters**: GPT-4.1-mini consistently outperforms GPT-4o-mini
   across all systems, sometimes by 10+ points.

---

## References

- Mnemis: https://arxiv.org/abs/2602.15313
- MAGMA: https://arxiv.org/abs/2601.03236
- AriadneMem: https://arxiv.org/abs/2603.03290
- LoCoMo: https://arxiv.org/abs/2402.17753
- LongMemEval: https://arxiv.org/abs/2410.10813
- Mem0: https://arxiv.org/abs/2504.19413
- Zep/Graphiti: https://github.com/getzep/graphiti
