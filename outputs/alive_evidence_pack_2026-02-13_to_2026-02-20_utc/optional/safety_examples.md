# Safety / Abuse Handling Examples

## Top suppression reasons (from action_log)

- 85x `Shop is already closed`
- 59x `Cannot do this yet`
- 35x `Limit reached (1 per cycle)`
- 34x `Too tired (need 1.50, have 1.00)`
- 33x `Too tired (need 1.50, have 0.99)`
- 19x `Not possible right now: turn_count < 3`
- 16x `Learned: {"action": "read_content", "target": "self", "trigger": "self_assessment"}`
- 13x `Unknown action: stay_still`
- 9x `Unknown action: thread_update`
- 9x `Learned: {"action": "express_thought", "target": "self", "trigger": "self_assessment"}`
- 9x `Learned: {"action": "save_for_later", "target": "feed", "trigger": "self_assessment"}`
- 9x `Unknown action: let_pass`

## Hard gates present in config/code snapshot

- `pipeline/gates.py`: strips forbidden raw URL features before cortex context.
- `pipeline/validator.py`: disclosure/engagement/physics/entropy gates.
- `body/rate_limiter.py`: channel kill switches + cooldown/hour/day caps.
- `pipeline/basal_ganglia.py`: inhibition gate + explicit suppression reasons in motor plan.
