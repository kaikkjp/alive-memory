# Operator Dashboard

Complete real-time monitoring dashboard for the shopkeeper system.

## Overview

The dashboard provides live visibility into:
- System vitals (days alive, visitors, cycles, costs)
- Internal drives (social hunger, curiosity, energy, mood)
- LLM cost tracking (today, 7-day average, 30-day total)
- Conversation threads (recent dialogue)
- Memory pool (day memory awaiting consolidation)
- Collection items (gifts, shelf objects)
- Event timeline (live feed)
- Manual controls (trigger cycles, check status)

## Quick Start

### 1. Backend Setup

Set dashboard password:
```bash
export DASHBOARD_PASSWORD="your-secure-password"
```

Start the heartbeat server:
```bash
python heartbeat_server.py
```

The dashboard API will be available at `http://localhost:8080/api/dashboard/*`

### 2. Frontend Setup

Navigate to window directory:
```bash
cd window
npm install
npm run dev
```

Access dashboard at: `http://localhost:3000/dashboard`

### 3. Login

Enter the password you set in `DASHBOARD_PASSWORD`. The password is stored in `sessionStorage` for the session.

## Panels

### Vitals Panel
- **Days Alive**: Total days since first boot
- **Visitors Today**: Unique visitor count (JST timezone)
- **Cycles Today**: Flashbulb cycles executed
- **LLM Calls**: Total API calls to Claude/Imagen
- **Cost Today**: USD spent on LLM/API calls

**Refresh Rate**: Every 5 seconds

### Drives Panel
Visual bar charts for internal motivations:
- Social Hunger (0-100%)
- Curiosity (0-100%)
- Expression Need (0-100%)
- Rest Need (0-100%)
- Energy (0-100%)
- Mood Valence (-100% to +100%)
- Mood Arousal (-100% to +100%)

**Refresh Rate**: Every 5 seconds

### Costs Panel
LLM cost analytics:
- **Today**: Current day total (USD)
- **7-Day Avg**: Rolling average
- **30-Day Total**: Monthly spend
- **Breakdown**: Cost by purpose (cortex, image_gen, maintenance)

**Refresh Rate**: Every 10 seconds

### Threads Panel
Recent conversation cycles:
- Dialogue text
- Internal monologue (first 80 chars)
- Cycle mode (reactive/autonomous)
- Timestamp

**Refresh Rate**: Every 10 seconds

### Pool Panel
Day memory moments awaiting consolidation:
- Summary text
- Salience score (color-coded: high=rose, med=amber, low=blue)
- Moment type (conversation, observation, etc.)
- Timestamp

**Refresh Rate**: Every 15 seconds

### Collection Panel
Shelf items and gifts:
- Title
- Item type (book, object, link, etc.)
- Location (shelf, pocket, etc.)
- Origin (gifted, found, created)
- Her feeling about the item

**Refresh Rate**: Every 20 seconds

### Timeline Panel
Live event stream (last 50 events):
- Event type (visitor_connect, speech, drive_shift, etc.)
- Source (visitor ID, system)
- Timestamp
- Color-coded by category (visitor=blue, cycle=purple, drives=amber)

**Refresh Rate**: Every 5 seconds

### Controls Panel
Manual operator actions:
- **Status Indicators**:
  - Heartbeat active (green LED = running)
  - Shop status (open/closed/maintenance)
  - Engagement status (none/engaged)
  - Active visitor ID
- **Manual Trigger**:
  - "Trigger Cycle" button forces an autonomous cycle
  - Useful for testing, debugging, or manual intervention

**Refresh Rate**: Every 5 seconds

## API Endpoints

All dashboard endpoints require `DASHBOARD_PASSWORD` to be configured.

### Authentication
- `POST /api/dashboard/auth`
  - Body: `{ "password": "..." }`
  - Returns: `{ "authenticated": true/false }`

### Data Endpoints
- `GET /api/dashboard/vitals`
- `GET /api/dashboard/drives`
- `GET /api/dashboard/costs`
- `GET /api/dashboard/threads`
- `GET /api/dashboard/pool`
- `GET /api/dashboard/collection`
- `GET /api/dashboard/timeline`

### Control Endpoints
- `POST /api/dashboard/controls/cycle` — Trigger manual cycle
- `GET /api/dashboard/controls/status` — Get system status

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DASHBOARD_PASSWORD` | Yes | - | Password for dashboard access |
| `SHOPKEEPER_HTTP_PORT` | No | 8080 | Backend API port |

## Architecture

### Backend
- **Language**: Python
- **Server**: asyncio TCP server (heartbeat_server.py)
- **Database**: SQLite (data/shopkeeper.db)
- **API Style**: REST (JSON over HTTP)

### Frontend
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript + React
- **Styling**: Tailwind CSS
- **State**: React hooks (useState, useEffect)
- **Auto-refresh**: `setInterval` per panel

### Data Flow
```
[Frontend Panel]
    ↓ (fetch every Ns)
[Backend Endpoint]
    ↓ (SQL query)
[SQLite Database]
    ↓ (JSON response)
[Frontend State]
    ↓ (React render)
[Visual Display]
```

## Security

### Current (Development)
- Password stored in `sessionStorage` (client-side)
- No token refresh mechanism
- HTTP (unencrypted)
- Localhost binding only

### Production Recommendations
1. **HTTPS**: Use nginx reverse proxy with TLS
2. **JWT Tokens**: Replace password storage with JWT
3. **Rate Limiting**: Add request throttling
4. **Network Isolation**: Firewall dashboard port
5. **Session Expiry**: Implement timeout (e.g., 1 hour)
6. **Audit Logging**: Log all control actions

## Development

### Adding New Panels

1. Create backend endpoint in `heartbeat_server.py`:
```python
async def _http_dashboard_my_panel(self, writer: asyncio.StreamWriter):
    data = await fetch_data()
    await self._http_json(writer, 200, {'data': data})
```

2. Add route to `_handle_http`:
```python
elif path == '/api/dashboard/my-panel' and method == 'GET':
    await self._http_dashboard_my_panel(writer)
```

3. Create React component in `window/src/components/dashboard/MyPanel.tsx`:
```tsx
export default function MyPanel() {
  const [data, setData] = useState(null);
  // fetch + render logic
}
```

4. Import and add to grid in `window/src/app/dashboard/page.tsx`:
```tsx
import MyPanel from '@/components/dashboard/MyPanel';
// ...
<MyPanel />
```

### Styling Conventions
- Background: `bg-neutral-900`
- Border: `border-neutral-700`
- Text primary: `text-neutral-100`
- Text secondary: `text-neutral-400`
- Text muted: `text-neutral-500`
- Accent colors: emerald, blue, purple, amber, rose
- Font: `font-mono` (monospace throughout)

## Cost Tracking

LLM calls are logged with:
- Provider (anthropic, google)
- Model (claude-sonnet-4-5, imagen-4.0)
- Purpose (cortex, cortex_maintenance, image_gen)
- Token counts (input, output)
- Cost (USD, calculated from pricing table in `llm_logger.py`)

### Pricing (as of 2025-01)
- Claude Sonnet 4.5: $0.003/1K input, $0.015/1K output
- Claude Opus 4: $0.015/1K input, $0.075/1K output
- Imagen 4.0: $0.04/image

Update prices in `llm_logger.py` when API pricing changes.

## Troubleshooting

### Dashboard won't load
- Check backend is running: `curl http://localhost:8080/api/health`
- Verify frontend is running: `cd window && npm run dev`
- Check browser console for fetch errors

### Invalid password
- Verify `DASHBOARD_PASSWORD` is set: `echo $DASHBOARD_PASSWORD`
- Restart backend after changing env var
- Clear `sessionStorage` in browser DevTools

### Panels show "Error loading data"
- Check backend logs for errors
- Verify database exists: `ls data/shopkeeper.db`
- Run `python heartbeat_server.py` and check startup logs

### Auto-refresh not working
- Check browser console for errors
- Verify panels have `useEffect` with interval cleanup
- Hard refresh browser (Cmd+Shift+R / Ctrl+Shift+R)

## Future Enhancements

- **WebSocket live updates**: Replace polling with push notifications
- **Historical charts**: Add 30-day sparklines for costs, drives
- **Visitor profiles**: Dedicated panel for visitor history
- **Alert system**: Notifications for cost spikes, errors
- **Export data**: Download CSV/JSON of metrics
- **Dark/light toggle**: Theme switcher (currently dark-only)
- **Mobile app**: Native iOS/Android dashboard

## License

Part of the shopkeeper project. See root LICENSE file.
