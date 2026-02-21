"""sim.visitors.templates — Dialogue templates for Tier 1 archetypes.

Templates are keyed by (archetype_id, goal, state) and return lists of
dialogue options. The state machine picks from these using the visitor's
RNG for deterministic replay.

Each template list contains 3-5 variations to avoid repetition across
visits by the same archetype type.
"""

from __future__ import annotations

from sim.visitors.models import VisitorState


# ---------------------------------------------------------------------------
# Template type: dict[archetype_id, dict[goal, dict[VisitorState, list[str]]]]
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, dict[VisitorState, list[str]]]] = {
    "regular_tanaka": {
        "buy": {
            VisitorState.ENTERING: [
                "Good afternoon. I was hoping you'd have something new in.",
                "Hey, it's me again. Anything interesting come in recently?",
                "Afternoon. I've been thinking about that card we discussed last time.",
            ],
            VisitorState.BROWSING: [
                "Hmm, let me look around for a bit.",
                "I'll take a look at what's on the shelves.",
                "Mind if I browse? I know my way around by now.",
            ],
            VisitorState.ENGAGING: [
                "This one catches my eye. What can you tell me about it?",
                "How much for this one? It looks like it's in good condition.",
                "I've been looking for something like this. What's the story behind it?",
            ],
            VisitorState.NEGOTIATING: [
                "That's a fair price. I'll take it.",
                "Hmm, a bit more than I expected. Could you do a little less?",
                "I appreciate you holding onto it for me. Let me think about it.",
            ],
            VisitorState.DECIDING: [
                "Alright, I'll go with this one.",
                "Let me think it over and come back.",
                "Thanks for showing me. I'll decide next time.",
            ],
            VisitorState.EXITING: [
                "Thanks as always. See you next week.",
                "Good doing business with you. Take care.",
                "I'll be back. Have a good evening.",
            ],
        },
        "chat": {
            VisitorState.ENTERING: [
                "Hey, just passing by. How's the day been?",
                "Afternoon. Quiet today, isn't it?",
            ],
            VisitorState.BROWSING: [
                "Just looking, really. More here to chat.",
                "I like the new arrangement. Looks good.",
            ],
            VisitorState.ENGAGING: [
                "Did you see the tournament results this weekend?",
                "I heard there's a new set coming out next month.",
                "Business been okay lately?",
            ],
            VisitorState.NEGOTIATING: [],  # Chat visitors don't negotiate
            VisitorState.DECIDING: [
                "Well, I should get going.",
                "Good talking to you.",
            ],
            VisitorState.EXITING: [
                "See you around, Tanaka out.",
                "Alright, catch you later. Take care of the shop.",
            ],
        },
    },
    "newbie_student": {
        "learn": {
            VisitorState.ENTERING: [
                "Um, excuse me... I'm new to trading cards. Is it okay to ask some questions?",
                "Hi! My friend told me this was a good place to learn about cards.",
                "Sorry to bother you. I don't know much about this stuff, but I'm curious.",
            ],
            VisitorState.BROWSING: [
                "Wow, there are so many... How do you even tell them apart?",
                "These look really old. Are they valuable?",
                "I had no idea there were this many different kinds.",
            ],
            VisitorState.ENGAGING: [
                "What makes a card rare exactly? Is it just how old it is?",
                "How did you learn so much about all this?",
                "If I wanted to start collecting, where should I begin?",
                "What's the most interesting card you've ever seen?",
            ],
            VisitorState.NEGOTIATING: [],
            VisitorState.DECIDING: [
                "This is really interesting. I want to learn more.",
                "I think I'll come back when I've done some research.",
            ],
            VisitorState.EXITING: [
                "Thank you so much! I learned a lot today.",
                "This was really cool. I'll definitely come back!",
                "Thanks for being so patient with my questions!",
            ],
        },
        "browse": {
            VisitorState.ENTERING: [
                "Hi! I just wanted to look around, if that's okay?",
                "Excuse me, can I just browse for a bit?",
            ],
            VisitorState.BROWSING: [
                "Everything looks so cool in here...",
                "Oh, I've seen this one in videos online!",
                "This shop has a nice atmosphere.",
            ],
            VisitorState.ENGAGING: [
                "What's this one? It looks different from the others.",
                "Do a lot of students come here?",
            ],
            VisitorState.NEGOTIATING: [],
            VisitorState.DECIDING: [
                "I should probably head to class soon.",
            ],
            VisitorState.EXITING: [
                "Thanks for letting me look around! Bye!",
                "I'll come back when I have more time. Thanks!",
            ],
        },
    },
    "whale_collector": {
        "buy": {
            VisitorState.ENTERING: [
                "I'm looking for something specific. First edition, mint condition.",
                "Good afternoon. I heard you might have some vintage stock I'm interested in.",
                "I collect seriously. Show me your best items.",
            ],
            VisitorState.BROWSING: [
                "These are decent. But I need something exceptional.",
                "Hmm. Condition is important to me. Let me inspect these.",
            ],
            VisitorState.ENGAGING: [
                "This one. What's the grade? Has it been authenticated?",
                "Interesting piece. What are you asking for it?",
                "I'd need to see documentation on the provenance.",
            ],
            VisitorState.NEGOTIATING: [
                "Price is fair if the condition is as described. I'll take it.",
                "I'd go higher if you can guarantee the grade.",
                "For this quality, the price works. Let's do it.",
            ],
            VisitorState.DECIDING: [
                "I'll take this one. Wrap it carefully, please.",
                "Not quite what I'm after today. I'll check back.",
            ],
            VisitorState.EXITING: [
                "Good transaction. I may return if you source more like this.",
                "Thank you. I appreciate a shop that knows quality.",
            ],
        },
    },
    "haggler_uncle": {
        "buy": {
            VisitorState.ENTERING: [
                "Hey, what kind of deals you got today?",
                "I'm looking for a bargain. What's on sale?",
                "Yo, I know this stuff. Don't try to overcharge me.",
            ],
            VisitorState.BROWSING: [
                "These prices... you serious? I can get these cheaper online.",
                "Let me see what's in the bargain bin.",
            ],
            VisitorState.ENGAGING: [
                "How about this one? What's your best price?",
                "Come on, it's got a crease right there. Knock some off.",
                "I'll buy three if you give me a discount.",
            ],
            VisitorState.NEGOTIATING: [
                "That's still too high. I'll do half that.",
                "Meet me in the middle and we got a deal.",
                "Last offer. Take it or I walk.",
                "Fine, fine. You drive a hard bargain.",
            ],
            VisitorState.DECIDING: [
                "Alright, alright. I'll take it at that price.",
                "Nah, forget it. Not paying that much.",
            ],
            VisitorState.EXITING: [
                "Yeah yeah, see you next time.",
                "I'll be back when you're feeling more generous.",
            ],
        },
    },
    "browser_tourist": {
        "browse": {
            VisitorState.ENTERING: [
                "Oh, what a cute little shop! Can I look around?",
                "Excuse me, is this a trading card store? How interesting!",
                "I'm just exploring the neighborhood. This place caught my eye.",
            ],
            VisitorState.BROWSING: [
                "These are so colorful! Are they all Japanese?",
                "Can I take a photo of the shop? It's very photogenic.",
                "My kids would love this place.",
            ],
            VisitorState.ENGAGING: [
                "Do you have anything that would make a good souvenir?",
                "How long has this shop been here?",
                "What are the most popular cards with tourists?",
            ],
            VisitorState.NEGOTIATING: [
                "Oh, that's a nice price. I'll get one as a gift.",
                "Do you accept credit cards?",
            ],
            VisitorState.DECIDING: [
                "I'll take this one as a souvenir!",
                "Everything is so nice, but I should keep moving.",
            ],
            VisitorState.EXITING: [
                "Thank you! What a lovely shop. Goodbye!",
                "I'll tell my friends about this place! Bye!",
                "What a charming experience. Arigatou!",
            ],
        },
    },
    "nostalgic_adult": {
        "buy": {
            VisitorState.ENTERING: [
                "I used to collect these as a kid... Haven't been in a shop like this in years.",
                "Hey. I've been feeling nostalgic lately. Thought I'd see what's around.",
                "My son started collecting, and it brought back memories. Got anything from the 90s?",
            ],
            VisitorState.BROWSING: [
                "Oh man, I remember this series. We used to trade these at school.",
                "This takes me back. The smell of the shop, the plastic sleeves...",
                "I can't believe some of these are still around.",
            ],
            VisitorState.ENGAGING: [
                "Do you have any from the original Pocket Monsters set?",
                "What's the story behind this shop? How'd you get into this?",
                "I had this exact card when I was twelve. What happened to those days...",
                "There's something about holding a physical card, you know?",
            ],
            VisitorState.NEGOTIATING: [
                "It's worth it for the memories. I'll take it.",
                "Money isn't really the point. It's the feeling.",
            ],
            VisitorState.DECIDING: [
                "Yeah, I'm getting this one. For old times' sake.",
                "I need to think about it. But I'll be back, for sure.",
            ],
            VisitorState.EXITING: [
                "Thanks for the trip down memory lane. Really.",
                "I'll bring my son next time. He'd love this place.",
                "Take care of this shop. Places like this are disappearing.",
            ],
        },
        "chat": {
            VisitorState.ENTERING: [
                "Hey. Long day at work. Mind if I just hang out for a bit?",
                "Afternoon. I've been thinking about the old days a lot lately.",
            ],
            VisitorState.BROWSING: [
                "Just looking. Being here is kind of therapeutic.",
            ],
            VisitorState.ENGAGING: [
                "Do you ever wonder why people collect things?",
                "I think it's about holding onto something, you know?",
                "My wife doesn't get it. She thinks it's just cardboard.",
            ],
            VisitorState.NEGOTIATING: [],
            VisitorState.DECIDING: [
                "Well, I should get back to the real world.",
            ],
            VisitorState.EXITING: [
                "Thanks for listening. See you around.",
                "This was nice. I needed this today.",
            ],
        },
    },
    "expert_rival": {
        "appraise": {
            VisitorState.ENTERING: [
                "Afternoon. I run a shop across town. Mind if I take a look at your stock?",
                "Heard you had some interesting pieces. Thought I'd see for myself.",
                "Professional curiosity. Let me see what you're working with.",
            ],
            VisitorState.BROWSING: [
                "Interesting arrangement. Different from how I'd do it.",
                "Hmm. You've got some gems buried in here.",
            ],
            VisitorState.ENGAGING: [
                "This grading is generous. I'd call it near-mint at best.",
                "Where did you source this one? The market's been dry lately.",
                "Your prices are competitive, I'll give you that.",
            ],
            VisitorState.NEGOTIATING: [],  # Rival doesn't buy
            VisitorState.DECIDING: [
                "Interesting shop. You know your stuff.",
                "Not bad. Different philosophy from mine, but it works.",
            ],
            VisitorState.EXITING: [
                "Good luck. The market's tough right now.",
                "See you around. Maybe at the next trade show.",
            ],
        },
    },
    "seller_cleaner": {
        "sell": {
            VisitorState.ENTERING: [
                "Hi, I have a box of cards I want to sell. My kid outgrew them.",
                "Excuse me, do you buy collections? I'm cleaning out my apartment.",
                "Someone told me these might be worth something. Can you take a look?",
            ],
            VisitorState.BROWSING: [
                "Here, let me show you what I've got.",
                "There's about a hundred cards in here. Mixed condition.",
            ],
            VisitorState.ENGAGING: [
                "So what do you think? Anything good in there?",
                "My son used to play with these every day. Are they still playable?",
                "I don't really know what they're worth. What would you offer?",
            ],
            VisitorState.NEGOTIATING: [
                "Is that the best you can do? They seemed worth more online.",
                "Alright, that sounds reasonable.",
                "Hmm, could you go a little higher? I was hoping for more.",
            ],
            VisitorState.DECIDING: [
                "Okay, let's do it. I just want them to go to a good home.",
                "Let me think about it. Maybe I'll keep the sentimental ones.",
            ],
            VisitorState.EXITING: [
                "Thanks for taking a look. I appreciate it.",
                "Good to know what they're worth. Thanks.",
            ],
        },
    },
    "kid_allowance": {
        "buy": {
            VisitorState.ENTERING: [
                "Hi! Do you have any cards under 500 yen?",
                "Excuse me! My friend said you have cool rare cards here!",
                "Um, I saved up my allowance. Can I buy something?",
            ],
            VisitorState.BROWSING: [
                "Whoa, look at all these! So cool!",
                "Do you have any holographic ones?",
                "This shop is way better than the convenience store.",
            ],
            VisitorState.ENGAGING: [
                "How much is this one? Is it strong in battles?",
                "My friend has a super rare one. Do you have anything that beats it?",
                "Can you teach me how to tell if a card is rare?",
            ],
            VisitorState.NEGOTIATING: [
                "I only have 800 yen... Is that enough?",
                "If I come back next week with more money, can you hold it for me?",
            ],
            VisitorState.DECIDING: [
                "I'll take this one! It's so cool!",
                "Aww, I don't have enough... Maybe next time.",
            ],
            VisitorState.EXITING: [
                "Thank you! I'm gonna show everyone at school!",
                "Bye! I'll come back when I get my allowance!",
                "This is the best shop ever! Bye!",
            ],
        },
        "browse": {
            VisitorState.ENTERING: [
                "Can I just look? I don't have much money today.",
                "Hi! I just wanna see the cool cards!",
            ],
            VisitorState.BROWSING: [
                "Whoa... I wish I could buy all of these.",
                "This one looks so powerful!",
            ],
            VisitorState.ENGAGING: [
                "What's the strongest card you've ever had?",
                "Do kids come here a lot?",
            ],
            VisitorState.NEGOTIATING: [],
            VisitorState.DECIDING: [
                "I gotta go home before it gets dark.",
            ],
            VisitorState.EXITING: [
                "Bye! I'll save up and come back!",
                "Thanks for letting me look! See ya!",
            ],
        },
    },
    "online_crossover": {
        "buy": {
            VisitorState.ENTERING: [
                "Hey! I saw your post online and had to come check this place out.",
                "Are you the one who runs the online account? I love your content!",
                "I followed you here from your last post. You mentioned some rare stock?",
            ],
            VisitorState.BROWSING: [
                "This place looks even better in person than in the photos.",
                "Oh, I saw this one in your post! It's still here!",
            ],
            VisitorState.ENGAGING: [
                "The card you featured last week — is that still available?",
                "Your taste is really good. What would you recommend for my collection?",
                "I trust your judgment on condition. What's the best piece right now?",
            ],
            VisitorState.NEGOTIATING: [
                "That's exactly what I expected from the quality. I'll take it.",
                "Can you do a small discount for a follower?",
            ],
            VisitorState.DECIDING: [
                "Definitely buying this. Can't wait to post about it.",
                "I'll think about it but I'll probably be back tomorrow.",
            ],
            VisitorState.EXITING: [
                "Thanks! I'm going to post about this visit. Great shop!",
                "This was worth the trip. I'll recommend you to the community.",
                "See you online! And maybe in person again soon.",
            ],
        },
        "chat": {
            VisitorState.ENTERING: [
                "Hey! Just wanted to meet you in person after following online.",
                "I'm a big fan of your posts. Had to come say hi.",
            ],
            VisitorState.BROWSING: [
                "The vibe in here is exactly what I imagined.",
            ],
            VisitorState.ENGAGING: [
                "How did you build such a following? Your content is really authentic.",
                "Do you get a lot of people visiting from your online posts?",
                "What's your favorite part about running a shop like this?",
            ],
            VisitorState.NEGOTIATING: [],
            VisitorState.DECIDING: [
                "This was awesome. Really glad I came.",
            ],
            VisitorState.EXITING: [
                "Thanks for the chat! I'll mention you in my next post.",
                "Great meeting you in person. Keep up the great content!",
            ],
        },
    },
}


def get_template(
    archetype_id: str, goal: str, state: VisitorState
) -> list[str]:
    """Get dialogue templates for a specific (archetype, goal, state) combo.

    Returns an empty list if no templates exist for the combination,
    which signals the state machine to skip dialogue for that state.
    """
    archetype_templates = TEMPLATES.get(archetype_id, {})
    goal_templates = archetype_templates.get(goal, {})
    return goal_templates.get(state, [])


# Fallback templates used when an archetype/goal combo lacks specific templates
FALLBACK_TEMPLATES: dict[str, dict[VisitorState, list[str]]] = {
    "buy": {
        VisitorState.ENTERING: [
            "Hello, I'm looking to buy some cards.",
            "Hi there. Got anything interesting?",
        ],
        VisitorState.BROWSING: [
            "Let me look around.",
        ],
        VisitorState.ENGAGING: [
            "How much for this one?",
            "What can you tell me about this card?",
        ],
        VisitorState.NEGOTIATING: [
            "That's a fair price.",
            "Hmm, a bit steep for me.",
        ],
        VisitorState.DECIDING: [
            "I'll take it.",
            "I need to think about it.",
        ],
        VisitorState.EXITING: [
            "Thanks. Goodbye.",
        ],
    },
    "sell": {
        VisitorState.ENTERING: [
            "Hi, I have some cards to sell.",
        ],
        VisitorState.BROWSING: [
            "Here's what I've got.",
        ],
        VisitorState.ENGAGING: [
            "What would you offer for these?",
        ],
        VisitorState.NEGOTIATING: [
            "Can you go a bit higher?",
        ],
        VisitorState.DECIDING: [
            "Alright, deal.",
        ],
        VisitorState.EXITING: [
            "Thanks for the appraisal.",
        ],
    },
    "browse": {
        VisitorState.ENTERING: [
            "Just looking around, if that's okay.",
        ],
        VisitorState.BROWSING: [
            "Nice selection you have here.",
        ],
        VisitorState.ENGAGING: [
            "What's this one?",
        ],
        VisitorState.NEGOTIATING: [],
        VisitorState.DECIDING: [
            "I should get going.",
        ],
        VisitorState.EXITING: [
            "Thanks. Nice shop.",
        ],
    },
    "learn": {
        VisitorState.ENTERING: [
            "Hi, I'm trying to learn about trading cards.",
        ],
        VisitorState.BROWSING: [
            "There's so much to take in.",
        ],
        VisitorState.ENGAGING: [
            "Can you explain how this works?",
        ],
        VisitorState.NEGOTIATING: [],
        VisitorState.DECIDING: [
            "I've learned a lot, thanks.",
        ],
        VisitorState.EXITING: [
            "Thanks for your time!",
        ],
    },
    "chat": {
        VisitorState.ENTERING: [
            "Hey, just wanted to chat.",
        ],
        VisitorState.BROWSING: [
            "Just hanging out.",
        ],
        VisitorState.ENGAGING: [
            "How's business been?",
        ],
        VisitorState.NEGOTIATING: [],
        VisitorState.DECIDING: [
            "Well, I should go.",
        ],
        VisitorState.EXITING: [
            "Good talk. See you.",
        ],
    },
    "appraise": {
        VisitorState.ENTERING: [
            "I'd like to get a card appraised.",
        ],
        VisitorState.BROWSING: [
            "Let me show you what I have.",
        ],
        VisitorState.ENGAGING: [
            "What do you think of the condition?",
        ],
        VisitorState.NEGOTIATING: [],
        VisitorState.DECIDING: [
            "Good to know the value.",
        ],
        VisitorState.EXITING: [
            "Thanks for the assessment.",
        ],
    },
    "trade": {
        VisitorState.ENTERING: [
            "Hi, I'm interested in trading.",
        ],
        VisitorState.BROWSING: [
            "Let me see what you have.",
        ],
        VisitorState.ENGAGING: [
            "Would you trade this for that?",
        ],
        VisitorState.NEGOTIATING: [
            "How about adding this to sweeten the deal?",
        ],
        VisitorState.DECIDING: [
            "Deal.",
        ],
        VisitorState.EXITING: [
            "Good trade. Thanks.",
        ],
    },
}


def get_template_with_fallback(
    archetype_id: str, goal: str, state: VisitorState
) -> list[str]:
    """Get templates, falling back to generic goal templates if needed."""
    templates = get_template(archetype_id, goal, state)
    if templates:
        return templates
    # Try fallback for this goal
    fallback_goal = FALLBACK_TEMPLATES.get(goal, {})
    return fallback_goal.get(state, [])
