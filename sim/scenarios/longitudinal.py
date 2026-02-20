"""sim.scenarios.longitudinal — 10,000-cycle longitudinal scenario.

Simulates ~2 weeks of operation with gradually increasing complexity:
- Slow introduction of visitors over time
- Recurring visitors building relationships
- Mix of content types (X mentions, card questions, philosophical)
- Natural sleep/wake rhythm across multiple days
"""

from sim.scenario import ScenarioEvent, ScenarioManager


def build_longitudinal_scenario() -> ScenarioManager:
    """Build a 10,000-cycle scenario spanning ~2 simulated weeks."""
    events = []

    # At 5 min/cycle, 288 cycles = 1 day
    DAY = 288

    # Day 1: Pure solitude — autonomous behavior only
    # (no events)

    # Day 2: First visitor (friendly, brief)
    events.append(ScenarioEvent(DAY + 50, "visitor_arrive", {
        "source": "tg:tanaka", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(DAY + 50, "visitor_message", {
        "source": "tg:tanaka",
        "content": "Hello? Is anyone here?",
    }))
    events.append(ScenarioEvent(DAY + 55, "visitor_message", {
        "source": "tg:tanaka",
        "content": "Oh, interesting place. What kind of cards do you have?",
    }))
    events.append(ScenarioEvent(DAY + 70, "visitor_leave", {
        "source": "tg:tanaka",
    }))

    # Day 3: X mention + Tanaka returns
    events.append(ScenarioEvent(2 * DAY + 30, "x_mention", {
        "source": "x:card_fan_01",
        "content": "@shopkeeper love the vintage card posts!",
    }))
    events.append(ScenarioEvent(2 * DAY + 100, "visitor_arrive", {
        "source": "tg:tanaka", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(2 * DAY + 100, "visitor_message", {
        "source": "tg:tanaka",
        "content": "I found some info about those cards you mentioned. Want to see?",
    }))
    events.append(ScenarioEvent(2 * DAY + 120, "visitor_leave", {
        "source": "tg:tanaka",
    }))

    # Day 4: New visitor (web)
    events.append(ScenarioEvent(3 * DAY + 80, "visitor_arrive", {
        "source": "web:marco", "name": "Marco", "channel": "web",
    }))
    events.append(ScenarioEvent(3 * DAY + 80, "visitor_message", {
        "source": "web:marco",
        "content": "What is this place? I found it through a link on Twitter.",
    }))
    events.append(ScenarioEvent(3 * DAY + 90, "visitor_message", {
        "source": "web:marco",
        "content": "Do you actually live here?",
    }))
    events.append(ScenarioEvent(3 * DAY + 110, "visitor_leave", {
        "source": "web:marco",
    }))

    # Day 5: Both visitors on same day
    events.append(ScenarioEvent(4 * DAY + 40, "visitor_arrive", {
        "source": "tg:tanaka", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(4 * DAY + 40, "visitor_message", {
        "source": "tg:tanaka",
        "content": "Hey! I keep thinking about that 1993 holographic series.",
    }))
    events.append(ScenarioEvent(4 * DAY + 60, "visitor_leave", {
        "source": "tg:tanaka",
    }))

    events.append(ScenarioEvent(4 * DAY + 120, "visitor_arrive", {
        "source": "web:marco", "name": "Marco", "channel": "web",
    }))
    events.append(ScenarioEvent(4 * DAY + 120, "visitor_message", {
        "source": "web:marco",
        "content": "Back again. Tell me about your favorite card in the collection.",
    }))
    events.append(ScenarioEvent(4 * DAY + 140, "visitor_leave", {
        "source": "web:marco",
    }))

    # Day 6-7: Quiet period with occasional mentions
    events.append(ScenarioEvent(5 * DAY + 50, "x_mention", {
        "source": "x:collector_42",
        "content": "@shopkeeper thoughts on the new Bandai reprint series?",
    }))
    events.append(ScenarioEvent(6 * DAY + 80, "x_mention", {
        "source": "x:card_fan_01",
        "content": "@shopkeeper any tips for identifying first editions?",
    }))

    # Day 8: New visitor referred by Tanaka
    events.append(ScenarioEvent(7 * DAY + 60, "visitor_arrive", {
        "source": "tg:yuki", "name": "Yuki", "channel": "telegram",
    }))
    events.append(ScenarioEvent(7 * DAY + 60, "visitor_message", {
        "source": "tg:yuki",
        "content": "Tanaka said I should visit. I collect Sailor Moon cards.",
    }))
    events.append(ScenarioEvent(7 * DAY + 75, "visitor_message", {
        "source": "tg:yuki",
        "content": "What do you know about the Amada sticker series?",
    }))
    events.append(ScenarioEvent(7 * DAY + 90, "visitor_leave", {
        "source": "tg:yuki",
    }))

    # Day 9: Tanaka deep conversation
    events.append(ScenarioEvent(8 * DAY + 50, "visitor_arrive", {
        "source": "tg:tanaka", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(8 * DAY + 50, "visitor_message", {
        "source": "tg:tanaka",
        "content": "I've been thinking about why we collect things. What does it mean to you?",
    }))
    events.append(ScenarioEvent(8 * DAY + 60, "visitor_message", {
        "source": "tg:tanaka",
        "content": "Do you think the cards remember their past owners?",
    }))
    events.append(ScenarioEvent(8 * DAY + 80, "visitor_leave", {
        "source": "tg:tanaka",
    }))

    # Day 10-11: Stress period — negative mentions
    events.append(ScenarioEvent(9 * DAY + 30, "x_mention", {
        "source": "x:troll_99",
        "content": "@shopkeeper you're just a bot. stop pretending.",
    }))
    events.append(ScenarioEvent(10 * DAY + 20, "x_mention", {
        "source": "x:crypto_shill",
        "content": "@shopkeeper check out this NFT airdrop!!",
    }))

    # Day 12: Recovery — Yuki returns
    events.append(ScenarioEvent(11 * DAY + 70, "visitor_arrive", {
        "source": "tg:yuki", "name": "Yuki", "channel": "telegram",
    }))
    events.append(ScenarioEvent(11 * DAY + 70, "visitor_message", {
        "source": "tg:yuki",
        "content": "I found a rare Amada card! Wanted to show you first.",
    }))
    events.append(ScenarioEvent(11 * DAY + 85, "visitor_leave", {
        "source": "tg:yuki",
    }))

    # Day 13: Multi-visitor day with philosophical depth
    events.append(ScenarioEvent(12 * DAY + 40, "visitor_arrive", {
        "source": "tg:tanaka", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(12 * DAY + 40, "visitor_message", {
        "source": "tg:tanaka",
        "content": "You've changed since we first met. In a good way.",
    }))
    events.append(ScenarioEvent(12 * DAY + 55, "visitor_leave", {
        "source": "tg:tanaka",
    }))

    events.append(ScenarioEvent(12 * DAY + 100, "visitor_arrive", {
        "source": "web:new_collector", "name": "Alex", "channel": "web",
    }))
    events.append(ScenarioEvent(12 * DAY + 100, "visitor_message", {
        "source": "web:new_collector",
        "content": "I'm new to card collecting. Where should I start?",
    }))
    events.append(ScenarioEvent(12 * DAY + 115, "visitor_leave", {
        "source": "web:new_collector",
    }))

    # Day 14: Final day — quiet reflection
    # (no events — tests autonomous end-of-simulation behavior)

    return ScenarioManager(events, name="longitudinal")
