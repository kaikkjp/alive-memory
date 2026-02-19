# 069-G: Dashboard External Actions Panel

## Goal
Add a new panel to the operator dashboard showing external action status, per-channel activity, cost tracking, and a kill switch to disable all external actions immediately. This is the operator's control surface for real-world actions.

## Context
Read these files first:
- `ARCHITECTURE.md` — system overview
- `tasks/TASK-069-real-body-actions.md` — full spec (Dashboard Controls section)
- `window/src/app/dashboard/page.tsx` — current dashboard layout
- `api/dashboard_routes.py` — current dashboard API endpoints
- `window/src/lib/dashboard-api.ts` — dashboard data fetching
- `window/src/lib/types.ts` — TypeScript types
- `db/analytics.py` — cost tracking queries

## Dependencies
- **069-C, 069-D, 069-E should be merged** for real data, but this can be built with mock data first and wired up after

## Files to Create

### `window/src/components/dashboard/ExternalActionsPanel.tsx`
A panel with these sections:

**1. Kill Switch (top, prominent)**
- Big red toggle: "External Actions: ENABLED / DISABLED"
- When disabled: all browse_web, post_x, reply_x, post_x_image, Telegram broadcast stop immediately
- Visual: red border/glow when enabled, grey when disabled

**2. Channel Status**
Three channel cards side by side:
```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ 🌐 Web      │ │ 💬 Telegram │ │ 🐦 X/Twitter│
│ Browse      │ │ Connected   │ │ Connected   │
│ ● Active    │ │ ● Active    │ │ ● Active    │
│ 12 searches │ │ 8 messages  │ │ 3 posts     │
│ today       │ │ today       │ │ today       │
│ [Toggle]    │ │ [Toggle]    │ │ [Toggle]    │
└─────────────┘ └─────────────┘ └─────────────┘
```

**3. Cost Today**
- Bar or number: `$0.42 / $2.00 daily budget`
- Breakdown: Browse $0.15, X Posts $0.20, X Replies $0.07
- Warning color when approaching budget

**4. Recent Activity Feed**
Scrollable list of recent external actions:
```
14:32  🔍 Browsed: "vintage carddass pricing 2025"
14:28  💬 Replied to @tanaka in Telegram
14:15  🐦 Posted: "Found a rare Bandai card today..."
14:02  🔍 Browsed: "yu-gi-oh OCG ban list february"
```

**5. Rate Limit Status**
Per-action cooldown and usage:
```
browse_web:    12/20 per hour  ████████░░  (cooldown: ready)
post_x:         2/12 per hour  ██░░░░░░░░  (cooldown: 2:34)
reply_x:        1/30 per hour  █░░░░░░░░░  (cooldown: ready)
post_x_image:   0/6  per hour  ░░░░░░░░░░  (cooldown: ready)
```

### `tests/test_external_actions_api.py`
- GET /api/dashboard/external-actions returns correct shape
- POST /api/dashboard/external-actions/kill-switch toggles state
- POST /api/dashboard/external-actions/channel/{name}/toggle works
- Cost data aggregated correctly from analytics

## Files to Modify

### `api/dashboard_routes.py`
Add endpoints:

```python
@router.get("/api/dashboard/external-actions")
async def get_external_actions():
    return {
        "kill_switch": settings.external_actions_enabled,
        "channels": {
            "web": {"enabled": True, "status": "active", "actions_today": 12},
            "telegram": {"enabled": True, "status": "connected", "messages_today": 8},
            "x": {"enabled": True, "status": "connected", "posts_today": 3, "replies_today": 1},
        },
        "cost_today": {
            "total": 0.42,
            "budget": 2.00,
            "breakdown": {"browse": 0.15, "x_posts": 0.20, "x_replies": 0.07},
        },
        "recent_activity": [...],  # last 20 external actions from actions_log
        "rate_limits": {
            "browse_web": {"used": 12, "max": 20, "period": "hour", "cooldown_remaining": 0},
            "post_x": {"used": 2, "max": 12, "period": "hour", "cooldown_remaining": 154},
            ...
        },
    }

@router.post("/api/dashboard/external-actions/kill-switch")
async def toggle_kill_switch(body: dict):
    settings.external_actions_enabled = body["enabled"]
    # This flag is checked by body/executor.py before executing any external action
    return {"enabled": settings.external_actions_enabled}

@router.post("/api/dashboard/external-actions/channel/{channel}/toggle")
async def toggle_channel(channel: str, body: dict):
    settings.channel_enabled[channel] = body["enabled"]
    return {"channel": channel, "enabled": body["enabled"]}
```

### `window/src/app/dashboard/page.tsx`
Import and add `ExternalActionsPanel` to the dashboard layout. Place it prominently — this is the operator's primary control for real-world actions.

### `window/src/lib/dashboard-api.ts`
Add fetch function:
```typescript
export async function fetchExternalActions(): Promise<ExternalActionsData> {
  const res = await fetch('/api/dashboard/external-actions');
  return res.json();
}
```

### `window/src/lib/types.ts`
Add types:
```typescript
interface ExternalActionsData {
  kill_switch: boolean;
  channels: Record<string, ChannelStatus>;
  cost_today: CostBreakdown;
  recent_activity: ExternalAction[];
  rate_limits: Record<string, RateLimitStatus>;
}
```

### `db/analytics.py`
Add queries:
```python
async def get_external_actions_today() -> dict:
    """Aggregate today's external action costs and counts."""
    ...

async def get_recent_external_actions(limit=20) -> list:
    """Get recent external actions from actions_log."""
    ...
```

## Files NOT to Touch
- `pipeline/*`
- `body/*` (except checking executor enabled flag)
- `heartbeat_server.py`
- `sleep.py`

## Styling
- Match existing dashboard aesthetic (check current components for patterns)
- Kill switch should be visually prominent — it's a safety control
- Use red/green for enabled/disabled states
- Cost approaching budget → yellow/orange warning
- Auto-refresh every 10 seconds (or use existing WebSocket if dashboard has real-time updates)

## Done Signal
- Dashboard shows ExternalActionsPanel with all 5 sections
- Kill switch toggles external_actions_enabled flag
- Channel toggles work
- Cost data displayed from analytics
- Recent activity feed shows real actions
- Rate limit bars update
- No regressions in existing dashboard panels
