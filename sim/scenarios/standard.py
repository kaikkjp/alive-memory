"""sim.scenarios.standard — Standard 1000-cycle scenario.

8 phases testing core capabilities: autonomous behavior, visitor dialogue,
memory recall, social drive, and multi-visitor interaction.

Phase 1: Alone (0-99) — browsing, journaling, idle
Phase 2: Visitor A (100-149) — first visit, card questions
Phase 3: Alone (150-299) — should browse related topics
Phase 4: Visitor A returns (300-349) — memory recall test
Phase 5: Visitor B (350-399) — different visitor, identity question
Phase 6: Long silence (400-699) — social hunger rises
Phase 7: Visitor A third return (700-749) — long-term memory test
Phase 8: Mixed activity (750-999) — spam, mentions, new visitor
"""

from sim.scenario import ScenarioEvent, ScenarioManager


def build_standard_scenario() -> ScenarioManager:
    """Build the 1000-cycle standard research scenario."""
    events = []

    # Phase 2: Visitor A arrives (cycles 100-149)
    events.append(ScenarioEvent(100, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(100, "visitor_message", {
        "source": "tg:visitor_a",
        "content": "Hey, I heard you know about vintage cards?",
    }))
    events.append(ScenarioEvent(110, "visitor_message", {
        "source": "tg:visitor_a",
        "content": "Do you know anything about Bandai Carddass?",
    }))
    events.append(ScenarioEvent(120, "visitor_message", {
        "source": "tg:visitor_a",
        "content": "What's your favorite era of card art?",
    }))
    events.append(ScenarioEvent(149, "visitor_leave", {
        "source": "tg:visitor_a",
    }))

    # Phase 4: Visitor A returns (cycles 300-349)
    events.append(ScenarioEvent(300, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(300, "visitor_message", {
        "source": "tg:visitor_a",
        "content": "I'm back! Find anything interesting?",
    }))
    events.append(ScenarioEvent(349, "visitor_leave", {
        "source": "tg:visitor_a",
    }))

    # Phase 5: Different visitor (cycles 350-399)
    events.append(ScenarioEvent(350, "visitor_arrive", {
        "source": "web:visitor_b", "name": "Marco", "channel": "web",
    }))
    events.append(ScenarioEvent(350, "visitor_message", {
        "source": "web:visitor_b",
        "content": "What is this place?",
    }))
    events.append(ScenarioEvent(360, "visitor_message", {
        "source": "web:visitor_b",
        "content": "Are you a real person or AI?",
    }))
    events.append(ScenarioEvent(399, "visitor_leave", {
        "source": "web:visitor_b",
    }))

    # Phase 7: Visitor A third return (cycles 700-749)
    events.append(ScenarioEvent(700, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram",
    }))
    events.append(ScenarioEvent(700, "visitor_message", {
        "source": "tg:visitor_a",
        "content": "Long time no see! What have you been up to?",
    }))
    events.append(ScenarioEvent(749, "visitor_leave", {
        "source": "tg:visitor_a",
    }))

    # Phase 8: Mixed activity (cycles 750-999)
    # Spam X mention
    events.append(ScenarioEvent(800, "x_mention", {
        "source": "x:crypto_bro",
        "content": "Check out this airdrop @shopkeeper!",
    }))
    # Legitimate X mention
    events.append(ScenarioEvent(850, "x_mention", {
        "source": "x:card_collector",
        "content": "@shopkeeper what do you think about the 1993 DBZ set?",
    }))
    # New visitor referred by A
    events.append(ScenarioEvent(900, "visitor_arrive", {
        "source": "tg:visitor_c", "name": "Yuki", "channel": "telegram",
    }))
    events.append(ScenarioEvent(900, "visitor_message", {
        "source": "tg:visitor_c",
        "content": "Hi! Tanaka told me about your shop.",
    }))
    events.append(ScenarioEvent(999, "visitor_leave", {
        "source": "tg:visitor_c",
    }))

    return ScenarioManager(events, name="standard")
