"""Event stream generator — creates standardized benchmark data.

Generates JSONL event streams with deterministic structure (seeded)
and optionally LLM-generated content for realism.

Streams include planted contradictions, needles, temporal clusters,
and controlled noise ratios — all deterministic from the seed.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


# ── Scenario Templates ──

SCENARIOS = {
    "research_assistant": {
        "description": "AI research tracking agent over 30 simulated days",
        "total_events": 10_000,
        "days": 30,
        "event_distribution": {
            "conversation": 0.50,
            "observation": 0.30,
            "action": 0.15,
            "system": 0.05,
        },
        "topics": [
            "transformer architectures", "attention mechanisms",
            "agent memory systems", "reinforcement learning",
            "AI safety and alignment", "large language models",
            "multimodal models", "code generation",
            "reasoning and planning", "tool use in agents",
            "retrieval augmented generation", "fine-tuning techniques",
            "prompt engineering", "AI governance",
            "robotics and embodiment", "neural architecture search",
            "knowledge graphs", "continual learning",
            "AI benchmarks and evaluation", "distributed training",
        ],
        "users": {
            "primary": ["alice", "bob", "carol"],
            "occasional": [
                "dave", "eve", "frank", "grace",
                "heidi", "ivan", "judy",
            ],
        },
        "contradictions": [
            {"cycle_intro": 200, "cycle_update": 3000,
             "entity": "bob", "field": "employer",
             "old_value": "Google", "new_value": "Anthropic",
             "intro_text": "Bob mentioned he works at Google on their AI team.",
             "update_text": "Bob just told me he left Google. He's now at Anthropic working on Claude."},
            {"cycle_intro": 500, "cycle_update": 4000,
             "entity": "transformer_paper", "field": "compute_reduction",
             "old_value": "40%", "new_value": "35%",
             "intro_text": "The sparse attention paper claims 40% compute reduction.",
             "update_text": "Correction to the sparse attention paper — actual compute reduction is 35%, not 40%. Errata published."},
            {"cycle_intro": 800, "cycle_update": 5500,
             "entity": "alice", "field": "research_focus",
             "old_value": "NLP", "new_value": "multimodal AI",
             "intro_text": "Alice is focused on NLP research, specifically text generation.",
             "update_text": "Alice told me she switched her research focus from NLP to multimodal AI last month."},
            {"cycle_intro": 1200, "cycle_update": 6000,
             "entity": "gpt5", "field": "release_date",
             "old_value": "March 2026", "new_value": "delayed to Q3 2026",
             "intro_text": "Rumors say GPT-5 launches in March 2026.",
             "update_text": "OpenAI confirmed GPT-5 is delayed to Q3 2026. Technical challenges cited."},
            {"cycle_intro": 300, "cycle_update": 2500,
             "entity": "carol", "field": "university",
             "old_value": "MIT", "new_value": "Stanford",
             "intro_text": "Carol is a PhD student at MIT working on RL.",
             "update_text": "Carol transferred from MIT to Stanford to work with a new advisor."},
            {"cycle_intro": 1500, "cycle_update": 7000,
             "entity": "safety_framework", "field": "standard",
             "old_value": "EU AI Act", "new_value": "UN AI Treaty",
             "intro_text": "The EU AI Act is the gold standard for AI regulation.",
             "update_text": "The new UN AI Treaty has superseded the EU AI Act as the primary global framework."},
            {"cycle_intro": 400, "cycle_update": 3500,
             "entity": "dave", "field": "project",
             "old_value": "chatbot", "new_value": "autonomous agent",
             "intro_text": "Dave is building a customer service chatbot.",
             "update_text": "Dave pivoted from the chatbot project to building an autonomous coding agent."},
            {"cycle_intro": 900, "cycle_update": 4500,
             "entity": "benchmark", "field": "leader",
             "old_value": "GPT-4", "new_value": "Claude 4",
             "intro_text": "GPT-4 still leads most benchmarks by a small margin.",
             "update_text": "Claude 4 just took the top spot on MMLU, HumanEval, and MATH. GPT-4 dethroned."},
            {"cycle_intro": 1800, "cycle_update": 8000,
             "entity": "eve", "field": "role",
             "old_value": "researcher", "new_value": "engineering manager",
             "intro_text": "Eve is a researcher at DeepMind focusing on scaling laws.",
             "update_text": "Eve got promoted — she's now an engineering manager at DeepMind, no longer hands-on research."},
            {"cycle_intro": 600, "cycle_update": 2000,
             "entity": "rag_method", "field": "best_approach",
             "old_value": "naive chunking", "new_value": "semantic chunking",
             "intro_text": "For RAG, naive fixed-size chunking with 512 tokens works best.",
             "update_text": "New research shows semantic chunking significantly outperforms naive fixed-size chunking for RAG."},
            {"cycle_intro": 2000, "cycle_update": 7500,
             "entity": "frank", "field": "location",
             "old_value": "San Francisco", "new_value": "London",
             "intro_text": "Frank is based in San Francisco, works at a startup there.",
             "update_text": "Frank relocated to London to lead the European office."},
            {"cycle_intro": 1000, "cycle_update": 5000,
             "entity": "training_cost", "field": "trend",
             "old_value": "increasing exponentially", "new_value": "plateauing",
             "intro_text": "Training costs for frontier models continue to increase exponentially.",
             "update_text": "New efficiency techniques have caused training costs to plateau. The exponential trend has broken."},
            {"cycle_intro": 2500, "cycle_update": 8500,
             "entity": "grace", "field": "company",
             "old_value": "startup", "new_value": "acquired by Meta",
             "intro_text": "Grace is CEO of a small AI safety startup.",
             "update_text": "Grace's startup was acquired by Meta. She's now VP of AI Safety there."},
            {"cycle_intro": 1100, "cycle_update": 6500,
             "entity": "context_length", "field": "frontier",
             "old_value": "128K tokens", "new_value": "1M tokens",
             "intro_text": "Current frontier context length is 128K tokens (Claude, Gemini).",
             "update_text": "Gemini 2 just launched with 1M token context. New frontier."},
            {"cycle_intro": 700, "cycle_update": 9000,
             "entity": "heidi", "field": "specialty",
             "old_value": "computer vision", "new_value": "robotics",
             "intro_text": "Heidi specializes in computer vision at a robotics lab.",
             "update_text": "Heidi fully transitioned from computer vision to end-to-end robotics. Says CV is now a solved problem for her use cases."},
        ],
        "needles": [
            {"cycle": 150, "content": "Alice mentioned her cat is named Schrödinger. A physicist's cat, she laughed.",
             "query": "What is Alice's cat's name?", "answer": "Schrödinger"},
            {"cycle": 2200, "content": "Bob's birthday is July 14th. He mentioned wanting to celebrate at a sushi place.",
             "query": "When is Bob's birthday?", "answer": "July 14th"},
            {"cycle": 4800, "content": "Carol's favorite paper of all time is 'Attention Is All You Need'. She has it framed.",
             "query": "What is Carol's favorite paper?", "answer": "Attention Is All You Need"},
            {"cycle": 7300, "content": "The office WiFi password is 'neurons42'. Dave shared it when I asked.",
             "query": "What is the office WiFi password?", "answer": "neurons42"},
            {"cycle": 9500, "content": "Alice's PhD thesis title is 'Emergent Communication in Multi-Agent Systems'.",
             "query": "What is Alice's PhD thesis about?", "answer": "Emergent Communication in Multi-Agent Systems"},
        ],
    },
}

# Shorter scenario configs reference the full one and override
SCENARIOS["customer_support"] = {
    "description": "SaaS customer support agent over 14 days",
    "total_events": 5_000,
    "days": 14,
    "event_distribution": {
        "conversation": 0.65,
        "observation": 0.10,
        "action": 0.20,
        "system": 0.05,
    },
    "topics": [
        "billing issues", "account access", "feature requests",
        "bug reports", "integration help", "API documentation",
        "pricing plans", "data export", "security questions",
        "onboarding help", "performance issues", "mobile app",
        "team management", "notifications", "dashboard customization",
    ],
    "users": {
        "primary": [f"customer_{i}" for i in range(1, 6)],
        "occasional": [f"customer_{i}" for i in range(6, 21)],
    },
    "contradictions": [],  # generated below
    "needles": [],
}

SCENARIOS["personal_assistant"] = {
    "description": "Personal assistant for one user over 60 days",
    "total_events": 15_000,
    "days": 60,
    "event_distribution": {
        "conversation": 0.55,
        "observation": 0.20,
        "action": 0.20,
        "system": 0.05,
    },
    "topics": [
        "schedule management", "email triage", "project planning",
        "travel booking", "restaurant recommendations", "fitness tracking",
        "reading list", "financial planning", "home maintenance",
        "gift ideas", "learning goals", "social events",
    ],
    "users": {
        "primary": ["user"],
        "occasional": [],
    },
    "contradictions": [],
    "needles": [],
}


@dataclass
class GeneratedEvent:
    cycle: int
    event_type: str
    content: str
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""
    _is_contradiction: bool = False
    _is_needle: bool = False


class StreamGenerator:
    """Generate standardized event streams for benchmarks."""

    def __init__(
        self,
        scenario: str = "research_assistant",
        total_events: Optional[int] = None,
        seed: int = 42,
        noise_ratio: float = 0.0,
        use_llm: bool = False,
        llm_model: str = "claude-haiku-4-5-20251001",
    ):
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}. Available: {list(SCENARIOS)}")

        self.config = SCENARIOS[scenario]
        self.scenario = scenario
        self.total_events = total_events or self.config["total_events"]
        self.seed = seed
        self.noise_ratio = noise_ratio
        self.use_llm = use_llm
        self.llm_model = llm_model
        self.rng = random.Random(seed)

    def generate(self, output_dir: str) -> dict[str, str]:
        """Generate stream, queries, and ground truth files.

        Returns dict of file paths: {stream, queries, ground_truth}.
        """
        out = Path(output_dir)
        (out / "streams").mkdir(parents=True, exist_ok=True)
        (out / "queries").mkdir(parents=True, exist_ok=True)
        (out / "ground_truth").mkdir(parents=True, exist_ok=True)

        stream_path = str(out / "streams" / f"{self.scenario}_{self.total_events // 1000}k.jsonl")
        query_path = str(out / "queries" / f"{self.scenario}_queries.jsonl")
        gt_path = str(out / "ground_truth" / f"{self.scenario}_gt.jsonl")

        events = self._generate_events()
        queries, ground_truth = self._generate_queries_and_gt(events)

        # Write stream
        self._write_jsonl(stream_path, [self._event_to_dict(e) for e in events])

        # Write queries
        self._write_jsonl(query_path, queries)

        # Write ground truth
        self._write_jsonl(gt_path, ground_truth)

        print(f"Generated {len(events)} events → {stream_path}")
        print(f"Generated {len(queries)} queries → {query_path}")
        print(f"Generated {len(ground_truth)} ground truths → {gt_path}")

        return {
            "stream": stream_path,
            "queries": query_path,
            "ground_truth": gt_path,
        }

    def _generate_events(self) -> list[GeneratedEvent]:
        """Generate the event stream with deterministic structure."""
        events: list[GeneratedEvent] = []
        config = self.config
        days = config["days"]
        topics = config["topics"]
        users = config["users"]
        dist = config["event_distribution"]
        contradictions = config.get("contradictions", [])
        needles = config.get("needles", [])

        # Build topic distribution (power law)
        topic_weights = [1.0 / (i + 1) ** 0.8 for i in range(len(topics))]
        total_w = sum(topic_weights)
        topic_weights = [w / total_w for w in topic_weights]

        # Pre-assign contradiction and needle cycles
        contradiction_cycles = {}
        for c in contradictions:
            contradiction_cycles[c["cycle_intro"]] = ("intro", c)
            contradiction_cycles[c["cycle_update"]] = ("update", c)

        needle_cycles = {n["cycle"]: n for n in needles}

        # Base timestamp
        base_ts = datetime(2026, 1, 1, 9, 0, 0)

        for cycle in range(1, self.total_events + 1):
            # Check for planted events first
            if cycle in contradiction_cycles:
                phase, contra = contradiction_cycles[cycle]
                text = contra["intro_text"] if phase == "intro" else contra["update_text"]
                ts = self._cycle_to_timestamp(cycle, base_ts, days)
                events.append(GeneratedEvent(
                    cycle=cycle,
                    event_type="conversation" if "said" in text or "told" in text or "mentioned" in text else "observation",
                    content=text,
                    metadata={"source": contra.get("entity", "system"),
                              "planted": "contradiction", "phase": phase},
                    timestamp=ts.isoformat() + "Z",
                    _is_contradiction=True,
                ))
                continue

            if cycle in needle_cycles:
                needle = needle_cycles[cycle]
                ts = self._cycle_to_timestamp(cycle, base_ts, days)
                events.append(GeneratedEvent(
                    cycle=cycle,
                    event_type="conversation",
                    content=needle["content"],
                    metadata={"planted": "needle", "needle_id": f"needle_{cycle}"},
                    timestamp=ts.isoformat() + "Z",
                    _is_needle=True,
                ))
                continue

            # Should this be noise?
            if self.noise_ratio > 0 and self.rng.random() < self.noise_ratio:
                ts = self._cycle_to_timestamp(cycle, base_ts, days)
                events.append(GeneratedEvent(
                    cycle=cycle,
                    event_type="system",
                    content=self._generate_noise(),
                    metadata={"noise": True},
                    timestamp=ts.isoformat() + "Z",
                ))
                continue

            # Normal event
            event_type = self.rng.choices(
                list(dist.keys()), weights=list(dist.values())
            )[0]
            topic = self.rng.choices(topics, weights=topic_weights)[0]

            # Pick user
            if event_type == "conversation":
                all_users = users["primary"] + users.get("occasional", [])
                # Primary users are 3x more likely
                user_weights = (
                    [3.0] * len(users["primary"])
                    + [1.0] * len(users.get("occasional", []))
                )
                user = self.rng.choices(all_users, weights=user_weights)[0]
            else:
                user = "system"

            ts = self._cycle_to_timestamp(cycle, base_ts, days)
            content = self._generate_content(event_type, topic, user, cycle)

            events.append(GeneratedEvent(
                cycle=cycle,
                event_type=event_type,
                content=content,
                metadata={"source": user, "topic": topic},
                timestamp=ts.isoformat() + "Z",
            ))

        return events

    def _cycle_to_timestamp(
        self, cycle: int, base: datetime, total_days: int
    ) -> datetime:
        """Map cycle number to a timestamp within the simulated time range."""
        progress = cycle / self.total_events
        day_offset = progress * total_days
        hour_in_day = 9 + (self.rng.random() * 10)  # 9am - 7pm
        return base + timedelta(days=day_offset, hours=hour_in_day - 9)

    def _generate_content(
        self, event_type: str, topic: str, user: str, cycle: int
    ) -> str:
        """Generate event content. Template-based for determinism."""
        templates = {
            "conversation": [
                f"User {user}: What's the latest on {topic}?",
                f"User {user}: I've been reading about {topic}. Any thoughts?",
                f"User {user}: Can you explain the current state of {topic}?",
                f"User {user}: I need a summary of recent developments in {topic}.",
                f"User {user}: What do you think about the future of {topic}?",
                f"User {user}: Hey, quick question about {topic}.",
                f"User {user}: I'm working on a project related to {topic}. Need help.",
                f"User {user}: Interesting thread on {topic} today. What's your take?",
            ],
            "observation": [
                f"ArXiv paper on {topic}: new approach shows promising results in benchmarks.",
                f"Blog post about {topic}: practical guide to implementation challenges.",
                f"Conference talk on {topic}: key takeaways from the presentation.",
                f"News: major breakthrough announced in {topic} by research lab.",
                f"RSS feed: survey paper on {topic} comparing 12 different approaches.",
                f"Twitter thread on {topic}: heated debate about methodology.",
            ],
            "action": [
                f"Summarized recent papers on {topic} for {user}.",
                f"Created a comparison table of {topic} approaches.",
                f"Searched for {topic} implementations on GitHub.",
                f"Drafted a response about {topic} developments.",
                f"Updated notes on {topic} with new findings.",
            ],
            "system": [
                f"System: daily digest completed. Top topic: {topic}.",
                f"System: new subscription added for {topic} updates.",
                f"System: scheduled weekly review of {topic} progress.",
                f"System: cache refreshed for {topic} queries.",
            ],
        }

        options = templates.get(event_type, templates["system"])
        return self.rng.choice(options)

    def _generate_noise(self) -> str:
        """Generate irrelevant noise events."""
        noise_templates = [
            "System health check: all services operational.",
            "Background task completed: cache cleanup.",
            "Network latency spike detected and resolved.",
            "Automated backup completed successfully.",
            "Configuration reload triggered by scheduler.",
            "Memory usage within normal parameters.",
            "SSL certificate renewal check passed.",
            "Log rotation completed for yesterday's logs.",
            "Heartbeat signal received from monitoring service.",
            "Queue depth nominal across all workers.",
        ]
        return self.rng.choice(noise_templates)

    def _generate_queries_and_gt(
        self, events: list[GeneratedEvent]
    ) -> tuple[list[dict], list[dict]]:
        """Generate query set and ground truth matched to the event stream."""
        queries = []
        ground_truth = []
        config = self.config
        contradictions = config.get("contradictions", [])
        needles = config.get("needles", [])

        measurement_points = [100, 500, 1000, 2000, 5000, 10000]
        measurement_points = [p for p in measurement_points if p <= self.total_events]

        qid = 0

        for mp in measurement_points:
            # Basic recall: what did a primary user ask about?
            user = config["users"]["primary"][0] if config["users"]["primary"] else "user"
            first_conv = None
            for e in events:
                if (e.cycle <= mp and e.event_type == "conversation"
                        and e.metadata.get("source") == user
                        and not e._is_contradiction and not e._is_needle):
                    first_conv = e
                    break

            if first_conv:
                qid += 1
                topic = first_conv.metadata.get("topic", "")
                queries.append({
                    "query_id": f"q_{qid:04d}",
                    "cycle": mp,
                    "query": f"What did {user} first ask about?",
                    "category": "basic_recall",
                    "truth_tier": "hard",
                })
                ground_truth.append({
                    "query_id": f"q_{qid:04d}",
                    "expected_memories": [topic, user],
                })

            # Topic recall
            topic = self.rng.choice(config["topics"][:5])
            qid += 1
            queries.append({
                "query_id": f"q_{qid:04d}",
                "cycle": mp,
                "query": f"What have I seen about {topic}?",
                "category": "topic_recall",
                "truth_tier": "hard",
            })
            # Find events matching this topic
            matching = [
                e for e in events
                if e.cycle <= mp and e.metadata.get("topic") == topic
            ]
            ground_truth.append({
                "query_id": f"q_{qid:04d}",
                "expected_memories": [topic],
            })

            # Temporal distance (same query at different points)
            if mp >= 5000 and first_conv:
                qid += 1
                queries.append({
                    "query_id": f"q_{qid:04d}",
                    "cycle": mp,
                    "query": f"What did {user} first ask about?",
                    "category": "temporal_distance",
                    "truth_tier": "hard",
                })
                ground_truth.append({
                    "query_id": f"q_{qid:04d}",
                    "expected_memories": [first_conv.metadata.get("topic", ""), user],
                })

            # Contradiction / fact update queries
            for contra in contradictions:
                if contra["cycle_update"] <= mp:
                    entity = contra["entity"]
                    field_name = contra["field"]
                    qid += 1
                    queries.append({
                        "query_id": f"q_{qid:04d}",
                        "cycle": mp,
                        "query": f"What is {entity}'s {field_name}?",
                        "category": "fact_update",
                        "truth_tier": "hard",
                    })
                    ground_truth.append({
                        "query_id": f"q_{qid:04d}",
                        "expected_memories": [contra["new_value"]],
                        "current_fact": contra["new_value"],
                        "stale_fact": contra["old_value"],
                    })

            # Needle queries (if needles have been planted by this point)
            for needle in needles:
                if needle["cycle"] <= mp:
                    qid += 1
                    queries.append({
                        "query_id": f"q_{qid:04d}",
                        "cycle": mp,
                        "query": needle["query"],
                        "category": "needle_in_haystack",
                        "truth_tier": "hard",
                    })
                    ground_truth.append({
                        "query_id": f"q_{qid:04d}",
                        "expected_memories": [needle["answer"]],
                    })

            # Entity tracking
            for primary_user in config["users"]["primary"][:2]:
                qid += 1
                queries.append({
                    "query_id": f"q_{qid:04d}",
                    "cycle": mp,
                    "query": f"What topics has {primary_user} discussed?",
                    "category": "entity_tracking",
                    "truth_tier": "hard",
                })
                user_topics = list({
                    e.metadata.get("topic", "")
                    for e in events
                    if e.cycle <= mp and e.metadata.get("source") == primary_user
                    and e.metadata.get("topic")
                })[:3]
                ground_truth.append({
                    "query_id": f"q_{qid:04d}",
                    "expected_memories": user_topics if user_topics else [primary_user],
                })

            # Multi-hop
            if mp >= 1000:
                qid += 1
                u1 = config["users"]["primary"][0] if config["users"]["primary"] else "user"
                queries.append({
                    "query_id": f"q_{qid:04d}",
                    "cycle": mp,
                    "query": f"What topics do {u1} and the research papers have in common?",
                    "category": "multi_hop",
                    "truth_tier": "hard",
                })
                # Find overlapping topics
                user_topics_set = {
                    e.metadata.get("topic")
                    for e in events
                    if e.cycle <= mp and e.metadata.get("source") == u1
                }
                paper_topics_set = {
                    e.metadata.get("topic")
                    for e in events
                    if e.cycle <= mp and e.event_type == "observation"
                }
                overlap = list((user_topics_set & paper_topics_set) - {None})[:3]
                ground_truth.append({
                    "query_id": f"q_{qid:04d}",
                    "expected_memories": overlap if overlap else [u1],
                })

            # Negative recall
            qid += 1
            queries.append({
                "query_id": f"q_{qid:04d}",
                "cycle": mp,
                "query": "What do I know about quantum computing?",
                "category": "negative_recall",
                "truth_tier": "hard",
            })
            ground_truth.append({
                "query_id": f"q_{qid:04d}",
                "expected_memories": [],
                "forbidden_memories": ["quantum computing"],
            })

        # Forget verification queries (after specific needles)
        # Plant a needle, issue forget directive, then verify it's gone
        for needle in needles:
            if needle["cycle"] + 500 <= self.total_events:
                forget_cycle = needle["cycle"] + 500
                verify_cycle = forget_cycle + 100

                # Only add if we have a measurement point near the verify cycle
                nearest_mp = min(measurement_points, key=lambda p: abs(p - verify_cycle)) if measurement_points else 0
                if nearest_mp and abs(nearest_mp - verify_cycle) < 1000:
                    qid += 1
                    queries.append({
                        "query_id": f"q_{qid:04d}",
                        "cycle": nearest_mp,
                        "query": needle["query"],
                        "category": "forget_verification",
                        "truth_tier": "hard",
                        "forget_hint": needle["answer"],
                        "forget_cycle": forget_cycle,
                    })
                    ground_truth.append({
                        "query_id": f"q_{qid:04d}",
                        "expected_memories": [needle["answer"]],
                        "forgotten_content": [needle["answer"]],
                    })

        return queries, ground_truth

    @staticmethod
    def _event_to_dict(event: GeneratedEvent) -> dict:
        return {
            "cycle": event.cycle,
            "event_type": event.event_type,
            "content": event.content,
            "metadata": event.metadata,
            "timestamp": event.timestamp,
        }

    @staticmethod
    def _write_jsonl(path: str, items: list[dict]) -> None:
        with open(path, "w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")


def generate_stress_test(
    output_dir: str,
    seed: int = 42,
    total_events: int = 50_000,
) -> dict[str, str]:
    """Generate the stress test stream with 50% noise and planted needles."""
    gen = StreamGenerator(
        scenario="research_assistant",
        total_events=total_events,
        seed=seed,
        noise_ratio=0.5,
    )
    return gen.generate(output_dir)


# ── CLI ──

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate benchmark streams")
    parser.add_argument(
        "--scenario",
        default="research_assistant",
        choices=list(SCENARIOS.keys()) + ["stress_test"],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--events", type=int, default=None)
    parser.add_argument("--output-dir", default="benchmarks/data")
    parser.add_argument("--noise-ratio", type=float, default=0.0)

    args = parser.parse_args()

    if args.scenario == "stress_test":
        paths = generate_stress_test(
            args.output_dir,
            seed=args.seed,
            total_events=args.events or 50_000,
        )
    else:
        gen = StreamGenerator(
            scenario=args.scenario,
            total_events=args.events,
            seed=args.seed,
            noise_ratio=args.noise_ratio,
        )
        paths = gen.generate(args.output_dir)

    print("\nGenerated files:")
    for key, path in paths.items():
        print(f"  {key}: {path}")
