"""Validator — two-stage: schema + physics/policy/entropy. No LLM.

Character-rule enforcement (canonical traits, voice rules) has been moved
to the metacognitive monitor in pipeline/output.py (Phase 3). The validator
now handles format/schema checks only. Character violations are detected
after the fact, not prevented.
"""

import re
from models.pipeline import (
    CortexOutput, ValidatorState, ValidatedOutput,
    ActionRequest, DroppedAction,
)

# Entropy state (module-level)
_recent_openings: list[str] = []


def validate(cortex_output: CortexOutput, state: ValidatorState,
             *, world=None) -> ValidatedOutput:
    """Stage 1: Schema. Stage 2: Physics + Policy + Entropy."""

    result = ValidatedOutput.from_cortex(cortex_output)
    has_physical = world.has_physical_space if world else True

    approved_actions: list[ActionRequest] = []
    dropped_actions: list[DroppedAction] = []

    # Stage 1: Schema defaults are handled by CortexOutput defaults.
    # Silence fallback: no dialogue and no actions → silence
    if not result.dialogue and not result.actions:
        result.dialogue = '...'

    # Stage 2: Engagement gate — block "alone" actions during conversation
    engaged_cycles = {'engage', 'micro'}
    if has_physical:
        alone_actions = {'write_journal', 'post_x_draft', 'rearrange', 'close_shop'}
    else:
        alone_actions = {'write_journal', 'post_x_draft'}

    # end_engagement is ALWAYS allowed during engaged cycles — it's the exit action
    exit_actions = {'end_engagement'}

    # Stage 2: Physics (hand state) — non-physical agents have no hands
    hands_required = {'write_journal', 'rearrange', 'post_x_draft'} if has_physical else set()

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
