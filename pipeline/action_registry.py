"""Action registry — capabilities the shopkeeper's body can perform.

Shared between Basal Ganglia (for gating) and Body (for execution).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
    ),
    'write_journal': ActionCapability(
        name='write_journal',
        enabled=True,
        energy_cost=0.05,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Write in journal',
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
    ),
    'post_x_draft': ActionCapability(
        name='post_x_draft',
        enabled=True,
        energy_cost=0.15,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Draft a post for X',
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
    'place_item': ActionCapability(
        name='place_item',
        enabled=True,
        energy_cost=0.02,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Put down an item she is holding',
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
    ),
}
