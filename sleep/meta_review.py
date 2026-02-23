"""Meta-sleep review — self-modification revert, trait stability, auto-promote.

Phase 4 of the sleep cycle:
- review_trait_stability()       — update trait stability from repetition patterns
- review_self_modifications()    — revert parameters if governed drives degraded
- Auto-promote high-frequency pending actions
"""

import sys

import clock
import db
from alive_config import cfg

# Drive fields governed by each parameter category — for meta-sleep review
_CATEGORY_DRIVE_MAP: dict[str, list[str]] = {
    'hypothalamus': ['mood_valence', 'social_hunger', 'curiosity', 'expression_need', 'energy', 'rest_need'],
    'thalamus':     ['curiosity'],
    'sensorium':    ['social_hunger'],
    'basal_ganglia': ['energy'],
    'output':       ['mood_valence', 'mood_arousal'],
    'sleep':        ['rest_need', 'energy'],
}


async def run_meta_review() -> None:
    """Run all meta-review phases: trait stability, self-modification revert, auto-promote.

    Uses late-bound references through the sleep package so tests can patch
    sleep.review_trait_stability etc.
    """
    _pkg = sys.modules['sleep']
    await _pkg.review_trait_stability()
    await _pkg.review_self_modifications()

    # Auto-promote high-frequency pending actions
    promoted = await db.promote_pending_actions(threshold=int(cfg('sleep_meta.auto_promote_threshold', 5)))
    if promoted:
        print(f"  [Sleep] Auto-promoted {len(promoted)} pending actions: {[a['action_name'] for a in promoted]}")


async def review_trait_stability():
    """Update trait stability based on repetition patterns."""
    active_traits = await db.get_all_active_traits()

    for trait in active_traits:
        observations = await db.get_trait_history(
            trait.visitor_id, trait.trait_category, trait.trait_key
        )

        window = int(cfg('sleep_meta.trait_recent_window', 3))
        if len(observations) >= window:
            # observations are DESC (most recent first)
            recent_three = observations[:window]
            consistent = all(
                o.trait_value == recent_three[0].trait_value
                for o in recent_three
            )
            if consistent:
                increment = cfg('sleep_meta.trait_stability_increment', 0.2)
                cap = cfg('sleep_meta.trait_stability_max', 1.0)
                new_stability = min(cap, trait.stability + increment)
                await db.update_trait_stability(trait.id, new_stability)

        # Check for unconfirmed anomalies (> 7 days old)
        if trait.status == 'anomaly':
            days_old = (clock.now_utc() - trait.observed_at).days
            if days_old > int(cfg('sleep_meta.anomaly_expiration_days', 7)):
                await db.update_trait_status(trait.id, 'archived')


async def review_self_modifications() -> None:
    """Review today's self-modifications. Revert per-parameter if its governed drive degraded.

    For each modified parameter, infer which drive(s) it governs from the
    parameter's category prefix. If that drive is more than 0.4 away from
    equilibrium, revert the parameter to its default.

    TECH DEBT v1: uses end-of-day drive state, not a before/after delta.
    Tune the 0.4 threshold after first experiment run.
    """
    from db.parameters import get_todays_self_modifications, reset_param
    from db.parameters import p_or as param_p_or

    mods = await get_todays_self_modifications()
    if not mods:
        print("  [Sleep] No self-modifications to review")
        return

    print(f"  [Sleep] Reviewing {len(mods)} self-modification(s)")
    drives = await db.get_drives_state()

    for mod in mods:
        param_key = mod['param_key']
        category = param_key.split('.')[0]
        governed_drives = _CATEGORY_DRIVE_MAP.get(category, [])

        degraded = False
        for drive_field in governed_drives:
            eq_key = f'hypothalamus.equilibria.{drive_field}'
            equilibrium = param_p_or(eq_key, 0.5)
            current = getattr(drives, drive_field, None)
            if current is None:
                continue
            deviation = abs(current - equilibrium)
            if deviation > cfg('sleep_meta.drive_deviation_threshold', 0.4):
                degraded = True
                print(f"    [Sleep] Drive {drive_field} deviation {deviation:.2f} — flagging {param_key} for revert")
                break

        if degraded:
            try:
                await reset_param(param_key, modified_by='meta_sleep_revert')
                print(f"    [Sleep] Reverted: {param_key} (was {mod['new_value']})")
            except Exception as e:
                print(f"    [Sleep] Failed to revert {param_key}: {e}")
        else:
            print(f"    [Sleep] Keeping: {param_key} (governed drives within range)")
