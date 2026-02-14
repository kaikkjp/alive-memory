"""Validator — two-stage: schema + physics/policy/entropy. No LLM."""

import re
from models.pipeline import (
    CortexOutput, ValidatorState, ValidatedOutput,
    ActionRequest, DroppedAction,
)

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


def validate(cortex_output: CortexOutput, state: ValidatorState) -> ValidatedOutput:
    """Stage 1: Schema. Stage 2: Physics + Policy + Entropy."""

    result = ValidatedOutput.from_cortex(cortex_output)

    approved_actions: list[ActionRequest] = []
    dropped_actions: list[DroppedAction] = []

    # Stage 1: Schema defaults are handled by CortexOutput defaults.
    # Silence fallback: no dialogue and no actions → silence
    if not result.dialogue and not result.actions:
        result.dialogue = '...'

    # Stage 2: Engagement gate — block "alone" actions during conversation
    engaged_cycles = {'engage', 'micro'}
    alone_actions = {'write_journal', 'post_x_draft', 'rearrange', 'close_shop'}

    # end_engagement is ALWAYS allowed during engaged cycles — it's the exit action
    exit_actions = {'end_engagement'}

    # Stage 2: Physics (hand state)
    hands_required = {'write_journal', 'rearrange', 'post_x_draft'}

    for action in result.actions:
        # end_engagement — guard against premature exits
        if action.type in exit_actions:
            if state.turn_count < 3:
                dropped_actions.append(DroppedAction(
                    action=action,
                    reason=f'end_engagement — too early (turn {state.turn_count}, min 3)',
                ))
                continue
            approved_actions.append(action)
            continue

        # Block alone actions during engaged conversation
        if (action.type in alone_actions
                and state.cycle_type in engaged_cycles
                and not (action.type == 'close_shop' and state.energy < 0.2)):
            dropped_actions.append(DroppedAction(
                action=action,
                reason=f'{action.type} — she\'s in conversation',
            ))
            # When journal is deferred, the desire to write builds up
            if action.type == 'write_journal':
                result.journal_deferred = True
            continue

        if action.type in hands_required and state.hands_held_item:
            dropped_actions.append(DroppedAction(
                action=action,
                reason=f'hands occupied with {state.hands_held_item}',
            ))
            # Inject diegetic line
            if not result.hand_warning:
                result.dialogue = (
                    (result.dialogue or '') +
                    ' ...let me put this down first.'
                ).strip()
                result.hand_warning = True
            continue

        approved_actions.append(action)

    # Stage 2: Disclosure gate
    dialogue = result.dialogue or ''
    dialogue = disclosure_gate(dialogue)
    result.dialogue = dialogue

    # Stage 2: Canonical consistency — remove contradicting sentences only
    dialogue = result.dialogue or ''
    cleaned, contradiction = canonical_consistency_check(dialogue)
    if contradiction:
        result.dialogue = cleaned
        result.canonical_contradiction = contradiction

    # Stage 2: Voice guardrails from character bible
    dialogue = result.dialogue or ''
    dialogue, voice_adjustments = enforce_voice_rules(dialogue, state.trust_level, result.expression)
    result.dialogue = dialogue
    if voice_adjustments:
        result.voice_adjustments = voice_adjustments

    # Stage 2: Entropy check
    result = entropy_check(result)

    result.approved_actions = approved_actions
    result.dropped_actions = dropped_actions

    return result


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


def entropy_check(output: ValidatedOutput) -> ValidatedOutput:
    """Prevent repetitive patterns."""
    global _recent_openings

    dialogue = output.dialogue or ''

    if dialogue and dialogue != '...':
        first_words = ' '.join(dialogue.split()[:5]).lower()
        if first_words in _recent_openings[-5:]:
            output.entropy_warning = f'Repeated opening: {first_words}'
        _recent_openings.append(first_words)
        _recent_openings = _recent_openings[-10:]

    return output
