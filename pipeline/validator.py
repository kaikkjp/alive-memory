"""Validator — two-stage: schema + physics/policy/entropy. No LLM."""

import re

# Entropy state (module-level)
_recent_openings: list[str] = []

# Canonical physical traits — things she cannot deny about herself.
# Each entry: (denial pattern, canonical truth to inject as internal reminder).
CANONICAL_TRAITS = [
    (re.compile(r"\b(i\s+do\s+not|i\s+don.?t|don.?t|no|never)\s+(wear|have|own)\s+glasses\b", re.I),
     "You wear glasses. Round, thin-framed."),
    (re.compile(r"\bi.?m\s+not\s+(short|small|petite)\b", re.I),
     "You're on the shorter side."),
]


def validate(cortex_output: dict, state: dict) -> dict:
    """Stage 1: Schema. Stage 2: Physics + Policy + Entropy."""

    approved_actions = []
    dropped_actions = []

    # Stage 1: Schema validation — ensure required fields
    cortex_output.setdefault('dialogue', None)
    cortex_output.setdefault('dialogue_language', 'en')
    cortex_output.setdefault('expression', 'neutral')
    cortex_output.setdefault('body_state', 'sitting')
    cortex_output.setdefault('gaze', 'at_visitor')
    cortex_output.setdefault('resonance', False)
    cortex_output.setdefault('actions', [])
    cortex_output.setdefault('memory_updates', [])
    cortex_output.setdefault('internal_monologue', '')

    if not cortex_output.get('dialogue') and not cortex_output.get('actions'):
        cortex_output['dialogue'] = '...'  # silence is valid

    # Stage 2: Engagement gate — block "alone" actions during conversation
    cycle_type = state.get('cycle_type', '')
    energy = state.get('energy', 1.0)
    engaged_cycles = {'engage', 'micro'}
    alone_actions = {'write_journal', 'post_x_draft', 'rearrange', 'close_shop'}

    # end_engagement is ALWAYS allowed during engaged cycles — it's the exit action
    exit_actions = {'end_engagement'}

    # Stage 2: Physics (hand state)
    hands_held = state.get('hands_held_item')
    hands_required = {'write_journal', 'rearrange', 'post_x_draft'}

    for action in cortex_output.get('actions', []):
        action_type = action.get('type', '')

        # end_engagement — guard against premature exits
        if action_type in exit_actions:
            turn_count = state.get('turn_count', 0)
            if turn_count < 3:
                dropped_actions.append({
                    'action': action,
                    'reason': f'end_engagement — too early (turn {turn_count}, min 3)',
                })
                continue
            approved_actions.append(action)
            continue

        # Block alone actions during engaged conversation
        if (action_type in alone_actions
                and cycle_type in engaged_cycles
                and not (action_type == 'close_shop' and energy < 0.2)):
            dropped_actions.append({
                'action': action,
                'reason': f'{action_type} — she\'s in conversation',
            })
            # When journal is deferred, the desire to write builds up
            if action_type == 'write_journal':
                cortex_output['_journal_deferred'] = True
            continue

        if action_type in hands_required and hands_held:
            dropped_actions.append({
                'action': action,
                'reason': f'hands occupied with {hands_held}',
            })
            # Inject diegetic line
            if not cortex_output.get('_hand_warning'):
                cortex_output['dialogue'] = (
                    (cortex_output.get('dialogue') or '') +
                    ' ...let me put this down first.'
                ).strip()
                cortex_output['_hand_warning'] = True
            continue

        approved_actions.append(action)

    # Stage 2: Disclosure gate
    dialogue = cortex_output.get('dialogue') or ''
    dialogue = disclosure_gate(dialogue)
    cortex_output['dialogue'] = dialogue

    # Stage 2: Canonical consistency — remove contradicting sentences only
    dialogue = cortex_output.get('dialogue') or ''
    cleaned, contradiction = canonical_consistency_check(dialogue)
    if contradiction:
        cortex_output['dialogue'] = cleaned
        cortex_output['_canonical_contradiction'] = contradiction

    # Stage 2: Voice guardrails from character bible
    dialogue = cortex_output.get('dialogue') or ''
    trust_level = state.get('trust_level', 'stranger')
    expression = cortex_output.get('expression', 'neutral')
    dialogue, voice_adjustments = enforce_voice_rules(dialogue, trust_level, expression)
    cortex_output['dialogue'] = dialogue
    if voice_adjustments:
        cortex_output['_voice_adjustments'] = voice_adjustments

    # Stage 2: Entropy check
    cortex_output = entropy_check(cortex_output)

    cortex_output['_approved_actions'] = approved_actions
    cortex_output['_dropped_actions'] = dropped_actions

    return cortex_output


def disclosure_gate(text: str) -> str:
    """Block assistant tropes and creepy precision."""

    BANNED_PHRASES = [
        'how can i help', 'feel free to', "i'd be happy to", "i\u2019d be happy to",
        'let me know if', 'is there anything', 'i understand your',
        "that's a great question", "that\u2019s a great question",
        'absolutely', 'of course!', 'no problem!', 'sure thing',
        'as an ai', 'as a language model', "i don't have feelings",
        "i don\u2019t have feelings", 'i appreciate', "that's interesting!",
        "that\u2019s interesting!", "great question",
    ]

    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in text_lower:
            text = re.sub(re.escape(phrase), '...', text, count=1, flags=re.IGNORECASE)

    return text


def canonical_consistency_check(dialogue: str) -> tuple[str, str | None]:
    """Check dialogue against canonical physical traits.

    Returns (cleaned_dialogue, contradiction_detail_or_None).
    Removes only the offending sentence(s), preserving the rest.
    """
    if not dialogue or dialogue == '...':
        return dialogue, None

    # Split into sentences (handles ., !, ? and ellipsis boundaries)
    sentences = re.split(r'(?<=[.!?])\s+', dialogue)
    contradiction = None

    cleaned = []
    for sentence in sentences:
        flagged = False
        for pattern, truth in CANONICAL_TRAITS:
            if pattern.search(sentence):
                contradiction = truth
                flagged = True
                break
        if not flagged:
            cleaned.append(sentence)

    result = ' '.join(cleaned).strip() if cleaned else '...'
    return result, contradiction


def enforce_voice_rules(dialogue: str, trust_level: str, expression: str) -> tuple[str, list[str]]:
    """Enforce non-negotiable voice rules deterministically."""
    adjustments: list[str] = []
    if not dialogue or dialogue == '...':
        return dialogue, adjustments

    text = dialogue

    # No "haha"/"lol" style assistant-ish laughter.
    laughter_pattern = re.compile(r'\b(?:haha+|lol+)\b', re.IGNORECASE)
    if laughter_pattern.search(text):
        text = laughter_pattern.sub('...', text)
        adjustments.append('removed_laughter')

    # Exclamation marks are only allowed when expression is "surprised".
    if expression != 'surprised' and '!' in text:
        text = re.sub(r'!+', '.', text)
        adjustments.append('removed_exclamation')

    # Hard sentence cap by trust level.
    max_sentences = {
        'stranger': 3,
        'returner': 5,
        'regular': 5,
    }.get(trust_level)

    if max_sentences is not None:
        sentences = [
            s.strip()
            for s in re.findall(r'[^.!?]+[.!?]?', text)
            if s.strip() and s.strip(' .!?')
        ]
        if len(sentences) > max_sentences:
            text = ' '.join(sentences[:max_sentences]).strip()
            adjustments.append(f'sentence_cap_{max_sentences}')

    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        text = '...'
    return text, adjustments


def entropy_check(output: dict) -> dict:
    """Prevent repetitive patterns."""
    global _recent_openings

    dialogue = output.get('dialogue', '')

    if dialogue and dialogue != '...':
        first_words = ' '.join(dialogue.split()[:5]).lower()
        if first_words in _recent_openings[-5:]:
            output['_entropy_warning'] = f'Repeated opening: {first_words}'
        _recent_openings.append(first_words)
        _recent_openings = _recent_openings[-10:]

    return output
