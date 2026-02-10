"""Validator — two-stage: schema + physics/policy/entropy. No LLM."""

# Entropy state (module-level)
_recent_openings: list[str] = []


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

        # end_engagement always passes — it's how she exits conversation
        if action_type in exit_actions:
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
            # Find the phrase case-insensitively and replace in original
            import re
            text = re.sub(re.escape(phrase), '...', text, count=1, flags=re.IGNORECASE)

    return text


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
