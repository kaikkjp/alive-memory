"""Intake pipeline: raw events → structured perceptions → day moments."""

from alive_memory.intake.affect import apply_affect, compute_valence
from alive_memory.intake.drives import update_drives, update_mood
from alive_memory.intake.file_watcher import FileWatcher
from alive_memory.intake.formation import form_moment
from alive_memory.intake.multimodal import perceive_media
from alive_memory.intake.thalamus import perceive

__all__ = [
    "perceive",
    "apply_affect",
    "compute_valence",
    "update_drives",
    "update_mood",
    "form_moment",
    "perceive_media",
    "FileWatcher",
]
