"""sim/ — Research simulation framework for ALIVE experiments.

Run controlled experiments: ALIVE vs baselines, ablation studies,
longitudinal development, and stress tests. Supports mock LLM (free,
deterministic) and cached LLM (real calls with response caching).

Usage:
    python -m sim.runner --variant full --scenario standard --cycles 1000 --llm mock
"""
