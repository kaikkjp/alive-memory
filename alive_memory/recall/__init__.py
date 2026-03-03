"""Recall pipeline: query → hot memory grep → RecallContext."""

from alive_memory.recall.hippocampus import recall
from alive_memory.recall.weighting import score_grep_result, decay_strength
from alive_memory.recall.context import mood_congruent_recall, drive_coupled_recall

__all__ = [
    "recall",
    "score_grep_result",
    "decay_strength",
    "mood_congruent_recall",
    "drive_coupled_recall",
]
