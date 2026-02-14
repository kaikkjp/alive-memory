"""Shared fixtures for the shopkeeper test suite."""

import asyncio
import sys
import os

import pytest

from models.pipeline import CortexOutput, ValidatorState

# Add project root to path so tests can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_cortex_output():
    """Minimal valid CortexOutput."""
    return CortexOutput(
        dialogue='The rain sounds different today.',
        dialogue_language='en',
        expression='neutral',
        body_state='sitting',
        gaze='at_window',
        resonance=False,
        internal_monologue='The sound on the roof has changed.',
    )


@pytest.fixture
def engaged_state():
    """ValidatorState simulating an engaged conversation."""
    return ValidatorState(
        cycle_type='engage',
        energy=0.6,
        hands_held_item=None,
        turn_count=5,
    )


@pytest.fixture
def alone_state():
    """ValidatorState simulating idle/alone time."""
    return ValidatorState(
        cycle_type='idle',
        energy=0.7,
        hands_held_item=None,
        turn_count=0,
    )
