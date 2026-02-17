"""Action registry — capabilities the shopkeeper's body can perform.

Shared between Basal Ganglia (for gating) and Body (for execution).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple, Optional


class PrereqResult(NamedTuple):
    """Result of a prerequisite check."""
    passed: bool
    failed: str  # empty string if passed, description of failure if not


def check_prerequisites(requires: list[str], context: dict) -> PrereqResult:
    """Check whether all prerequisites for an action are met.

    Context keys: visitor_present (bool), turn_count (int), mode (str).
    """
    if not requires:
        return PrereqResult(passed=True, failed='')

    for req in requires:
        if req == 'visitor_present':
            if not context.get('visitor_present', False):
                return PrereqResult(passed=False, failed='no visitor present')
        elif req.startswith('turn_count'):
            # Parse "turn_count >= N"
            match = re.match(r'turn_count\s*>=\s*(\d+)', req)
            if match:
                threshold = int(match.group(1))
                if context.get('turn_count', 0) < threshold:
                    return PrereqResult(passed=False, failed=f'turn_count < {threshold}')
        elif req == 'wallet_connected':
            if not context.get('wallet_connected', False):
                return PrereqResult(passed=False, failed='wallet not connected')
        elif req == 'budget_remaining':
            if not context.get('budget_remaining', False):
                return PrereqResult(passed=False, failed='no budget remaining')
        elif req == 'valid_content_id':
            if not context.get('content_id'):
                return PrereqResult(passed=False, failed='no content_id provided')
        else:
            return PrereqResult(passed=False, failed=f'unknown prerequisite: {req}')

    return PrereqResult(passed=True, failed='')


@dataclass
class ActionCapability:
    """Describes what the body can do and its constraints."""
    name: str
    enabled: bool
    energy_cost: float
    cooldown_seconds: int = 0
    last_used: Optional[datetime] = None
    max_per_cycle: int = 1
    requires: list[str] = field(default_factory=list)
    description: str = ''
    generative: bool = False  # True = needs LLM output (speak, journal, post)


ACTION_REGISTRY: dict[str, ActionCapability] = {
    # ── Currently enabled actions ──
    'speak': ActionCapability(
        name='speak',
        enabled=True,
        energy_cost=0.15,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present'],
        description='Speak to the visitor',
        generative=True,
    ),
    'write_journal': ActionCapability(
        name='write_journal',
        enabled=True,
        energy_cost=0.05,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Write in journal',
        generative=True,
    ),
    'rearrange': ActionCapability(
        name='rearrange',
        enabled=True,
        energy_cost=0.1,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Rearrange items on the shelf',
    ),
    'express_thought': ActionCapability(
        name='express_thought',
        enabled=True,
        energy_cost=0.02,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Hold a thought internally',
    ),
    'end_engagement': ActionCapability(
        name='end_engagement',
        enabled=True,
        energy_cost=0.0,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present', 'turn_count >= 3'],
        description='End the conversation',
    ),
    'accept_gift': ActionCapability(
        name='accept_gift',
        enabled=True,
        energy_cost=0.1,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present'],
        description='Accept a gift from the visitor',
    ),
    'decline_gift': ActionCapability(
        name='decline_gift',
        enabled=True,
        energy_cost=0.02,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present'],
        description='Decline a gift from the visitor',
    ),
    'show_item': ActionCapability(
        name='show_item',
        enabled=True,
        energy_cost=0.05,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present'],
        description='Show an item to the visitor',
        generative=True,
    ),
    'post_x_draft': ActionCapability(
        name='post_x_draft',
        enabled=True,
        energy_cost=0.15,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Draft a post for X',
        generative=True,
    ),
    'close_shop': ActionCapability(
        name='close_shop',
        enabled=True,
        energy_cost=0.0,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Close the shop',
    ),
    'open_shop': ActionCapability(
        name='open_shop',
        enabled=True,
        energy_cost=0.0,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Open the shop',
    ),
    'place_item': ActionCapability(
        name='place_item',
        enabled=True,
        energy_cost=0.02,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Put down an item she is holding',
    ),
    'read_content': ActionCapability(
        name='read_content',
        enabled=True,
        energy_cost=1.5,
        cooldown_seconds=360,  # ~2 cycles at 3min/cycle
        max_per_cycle=1,
        requires=[],
        description='Read a content item from the feed',
        generative=True,
    ),
    'save_for_later': ActionCapability(
        name='save_for_later',
        enabled=True,
        energy_cost=0.0,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Save a content item for later reading',
    ),
    'mention_in_conversation': ActionCapability(
        name='mention_in_conversation',
        enabled=True,
        energy_cost=0.5,
        cooldown_seconds=0,
        max_per_cycle=2,
        requires=[],
        description='Reference a content item title/topic in conversation without full read',
    ),

    # ── Future actions (disabled) ──
    'browse_web': ActionCapability(
        name='browse_web',
        enabled=False,
        energy_cost=0.2,
        cooldown_seconds=300,
        max_per_cycle=1,
        requires=[],
        description='Look something up online',
    ),
    'post_x': ActionCapability(
        name='post_x',
        enabled=False,
        energy_cost=0.15,
        cooldown_seconds=3600,
        max_per_cycle=1,
        requires=[],
        description='Post on X',
        generative=True,
    ),
    'watch_video': ActionCapability(
        name='watch_video',
        enabled=False,
        energy_cost=0.25,
        cooldown_seconds=600,
        max_per_cycle=1,
        requires=[],
        description='Watch a video',
    ),
    'search_marketplace': ActionCapability(
        name='search_marketplace',
        enabled=False,
        energy_cost=0.2,
        cooldown_seconds=300,
        max_per_cycle=1,
        requires=[],
        description='Search for items to acquire',
    ),
    'make_purchase': ActionCapability(
        name='make_purchase',
        enabled=False,
        energy_cost=0.3,
        cooldown_seconds=1800,
        max_per_cycle=1,
        requires=['wallet_connected', 'budget_remaining'],
        description='Purchase an item',
    ),
    'send_message': ActionCapability(
        name='send_message',
        enabled=False,
        energy_cost=0.1,
        cooldown_seconds=60,
        max_per_cycle=1,
        requires=[],
        description='Send a message',
        generative=True,
    ),
}
