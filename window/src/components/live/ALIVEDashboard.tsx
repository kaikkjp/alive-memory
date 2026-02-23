'use client';

import { useState, useEffect } from 'react';

// ─── Types ───

interface LiveUptime {
  started_at: string | null;
  totalCycles: number;
}

interface LiveDrives {
  social_hunger: number;
  curiosity: number;
  expression_need: number;
  rest_need: number;
  energy: number;
  mood_valence: number;
  mood_arousal: number;
}

interface LiveAction {
  time: string;
  action: string;
  detail: string;
  type: string;
}

interface LiveThread {
  title: string;
  type: string;
  age: string;
  priority: number;
}

interface LiveMemory {
  totalImpressions: number;
  totalTraits: number;
  totems: number;
  selfDiscoveries: number;
  journals: number;
}

interface LiveSleep {
  quality: number;
  dreamsConsolidated: number;
  memoriesStrengthened: number;
  hoursAgo: number;
}

interface LiveVisitors {
  today: number;
  total: number;
  returning: number;
  currentlyPresent: number;
}

interface LiveDashboardState {
  uptime: LiveUptime;
  status: string;
  expression: string;
  bodyState: string;
  gaze: string;
  shopOpen: boolean;
  timeOfDay: string;
  costToday: number;
  cost30d: number;
  drives: LiveDrives;
  recentActions: LiveAction[];
  threads: LiveThread[];
  memory: LiveMemory;
  inhibitions: string[];
  lastSleep: LiveSleep;
  visitors: LiveVisitors;
  monologue: string;
}

// ─── Constants ───

const DRIVE_META: Record<string, { label: string; icon: string; color: string; desc: string }> = {
  social_hunger: { label: 'Social Hunger', icon: '◎', color: '#e8927c', desc: 'Need for human connection' },
  curiosity: { label: 'Curiosity', icon: '✧', color: '#7cc4e8', desc: 'Drive to explore and learn' },
  expression_need: { label: 'Expression', icon: '◈', color: '#c49ee8', desc: 'Urge to create and express' },
  rest_need: { label: 'Rest Need', icon: '◌', color: '#8b9dc3', desc: 'Physical need for sleep' },
  energy: { label: 'Energy', icon: '◉', color: '#e8d07c', desc: 'Available vitality' },
  mood_valence: { label: 'Mood', icon: '◐', color: '#7ce8a3', desc: 'Emotional valence: negative (blue) ← neutral → positive (green)' },
  mood_arousal: { label: 'Arousal', icon: '◑', color: '#e87c9e', desc: 'Activation level' },
};

const ACTION_COLORS: Record<string, string> = {
  social: '#e8927c',
  explore: '#7cc4e8',
  express: '#c49ee8',
  maintain: '#8b9dc3',
  inner: '#7ce8a3',
};

const BIPOLAR_DRIVES = new Set(['mood_valence']);

const API_BASE = process.env.NEXT_PUBLIC_DASHBOARD_API_URL || '';

// ─── Components ───

function DriveBar({ name, value, meta }: { name: string; value: number; meta: typeof DRIVE_META[string] }) {
  const isBipolar = BIPOLAR_DRIVES.has(name);

  if (isBipolar) {
    const clamped = Math.max(-1, Math.min(1, value));
    const pct = Math.round(Math.abs(clamped) * 100);
    const isPositive = clamped >= 0;
    const barColor = isPositive ? '#7ce8a3' : '#8b9dc3';
    const label = isPositive ? `+${clamped.toFixed(2)}` : `${clamped.toFixed(2)}`;
    const barWidthPct = Math.abs(clamped) * 50;

    return (
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
          <span style={{ fontSize: 11, color: '#9a9a9a', letterSpacing: '0.05em' }}>
            <span style={{ color: meta.color, marginRight: 6 }}>{meta.icon}</span>
            {meta.label}
          </span>
          <span style={{ fontSize: 11, color: barColor, fontFamily: "'JetBrains Mono', monospace" }}>
            {label}
          </span>
        </div>
        <div style={{ height: 3, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden', position: 'relative' }}>
          <div style={{ position: 'absolute', left: '50%', top: 0, width: 1, height: '100%', background: '#333', zIndex: 2 }} />
          <div style={{
            position: 'absolute',
            left: isPositive ? '50%' : `${50 - barWidthPct}%`,
            width: `${barWidthPct}%`,
            height: '100%',
            background: `linear-gradient(${isPositive ? '90deg' : '270deg'}, ${barColor}44, ${barColor})`,
            borderRadius: 2,
            transition: 'all 1.5s ease',
            boxShadow: pct > 60 ? `0 0 8px ${barColor}66` : 'none',
          }} />
        </div>
      </div>
    );
  }

  const pct = Math.round(value * 100);
  const isHigh = value > 0.7;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
        <span style={{ fontSize: 11, color: '#9a9a9a', letterSpacing: '0.05em' }}>
          <span style={{ color: meta.color, marginRight: 6 }}>{meta.icon}</span>
          {meta.label}
        </span>
        <span style={{ fontSize: 11, color: isHigh ? meta.color : '#666', fontFamily: "'JetBrains Mono', monospace" }}>
          {pct}%
        </span>
      </div>
      <div style={{ height: 3, background: '#1a1a1a', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: `linear-gradient(90deg, ${meta.color}44, ${meta.color})`,
          borderRadius: 2,
          transition: 'width 1.5s ease',
          boxShadow: isHigh ? `0 0 8px ${meta.color}66` : 'none',
        }} />
      </div>
    </div>
  );
}

function PulsingDot({ color = '#4ade80', size = 8 }: { color?: string; size?: number }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: color,
        boxShadow: `0 0 ${size}px ${color}88`,
        animation: 'pulse 2s ease-in-out infinite',
      }} />
    </span>
  );
}

function ActionItem({ action }: { action: LiveAction }) {
  const color = ACTION_COLORS[action.type] || '#666';
  return (
    <div style={{ padding: '8px 0', borderBottom: '1px solid #ffffff06', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <span style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace", minWidth: 58, paddingTop: 2 }}>
        {action.time}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{
            fontSize: 9, color: color, background: `${color}15`, padding: '1px 6px',
            borderRadius: 3, letterSpacing: '0.06em', textTransform: 'uppercase',
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            {action.action}
          </span>
        </div>
        <span style={{ fontSize: 12, color: '#b0b0b0', lineHeight: 1.4 }}>
          {action.detail}
        </span>
      </div>
    </div>
  );
}

// ─── Main Dashboard ───

export default function ALIVEDashboard() {
  const [state, setState] = useState<LiveDashboardState | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [hoveredDrive, setHoveredDrive] = useState<string | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);

  // Fetch live data
  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/live`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setState(data);
        setElapsed(0); // reset uptime ticker on fresh data
        setConnectionLost(false);
      } catch {
        setConnectionLost(true);
      }
    };
    fetchState();
    const interval = setInterval(fetchState, 30000);
    return () => clearInterval(interval);
  }, []);

  // Uptime ticker
  useEffect(() => {
    const interval = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  if (!state) {
    return (
      <div style={{ minHeight: '100vh', background: '#0a0a0a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: connectionLost ? '#e87c7c' : '#555', fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>
          {connectionLost ? 'connection lost — retrying...' : 'Loading...'}
        </div>
      </div>
    );
  }

  // Calculate uptime from started_at
  let uptimeSeconds = elapsed;
  if (state.uptime.started_at) {
    const startedMs = new Date(state.uptime.started_at).getTime();
    const nowMs = Date.now();
    uptimeSeconds = Math.floor((nowMs - startedMs) / 1000);
  }
  const days = Math.floor(uptimeSeconds / 86400);
  const hours = Math.floor((uptimeSeconds % 86400) / 3600);
  const minutes = Math.floor((uptimeSeconds % 3600) / 60);
  const secs = uptimeSeconds % 60;

  const statusColor = state.status === 'awake' ? '#4ade80' : state.status === 'sleeping' ? '#8b9dc3' : '#c49ee8';
  const statusLabel = state.status === 'awake' ? 'Awake' : state.status === 'sleeping' ? 'Sleeping' : 'Dreaming';

  return (
    <div style={{
      minHeight: '100vh', background: '#0a0a0a', color: '#e0e0e0',
      fontFamily: "'Crimson Pro', 'Georgia', serif", position: 'relative', overflow: 'hidden',
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&family=JetBrains+Mono:wght@300;400&display=swap');
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes breathe { 0%, 100% { opacity: 0.03; } 50% { opacity: 0.06; } }
        @keyframes monologueGlow { 0%, 100% { border-color: #ffffff08; } 50% { border-color: #ffffff14; } }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
      `}</style>

      {/* Atmospheric background */}
      <div style={{
        position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none',
        background: 'radial-gradient(ellipse at 30% 20%, #1a120a11 0%, transparent 60%), radial-gradient(ellipse at 70% 80%, #0a121a11 0%, transparent 60%)',
        animation: 'breathe 8s ease-in-out infinite',
      }} />

      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1100, margin: '0 auto', padding: '40px 24px' }}>

        {/* Connection lost indicator */}
        {connectionLost && (
          <div style={{
            position: 'fixed', top: 16, right: 16, zIndex: 10,
            fontSize: 10, color: '#e87c7c', fontFamily: "'JetBrains Mono', monospace",
            background: '#1a0a0a', padding: '6px 12px', borderRadius: 4, border: '1px solid #e87c7c33',
          }}>
            connection lost
          </div>
        )}

        {/* Header */}
        <header style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
          marginBottom: 48, animation: 'fadeIn 0.6s ease',
        }}>
          <div>
            <h1 style={{
              fontSize: 13, fontWeight: 400, letterSpacing: '0.15em', color: '#666',
              textTransform: 'uppercase', marginBottom: 6, fontFamily: "'JetBrains Mono', monospace",
            }}>
              The Shopkeeper
            </h1>
            <div style={{ fontSize: 11, color: '#444', fontFamily: "'JetBrains Mono', monospace" }}>
              ALIVE Cognitive Architecture · Single-call autonomous agent
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end', marginBottom: 4 }}>
              <PulsingDot color={statusColor} />
              <span style={{ fontSize: 12, color: statusColor, fontFamily: "'JetBrains Mono', monospace" }}>
                {statusLabel}
              </span>
            </div>
            <div style={{ fontSize: 10, color: '#444', fontFamily: "'JetBrains Mono', monospace" }}>
              {state.shopOpen ? 'Shop Open' : 'Shop Closed'} · {state.timeOfDay}
            </div>
          </div>
        </header>

        {/* Uptime & Core Stats */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 1, marginBottom: 32,
          background: '#ffffff06', borderRadius: 8, overflow: 'hidden', animation: 'fadeIn 0.8s ease',
        }}>
          {[
            { label: 'Alive for', value: `${days}d ${hours}h ${minutes}m ${secs}s`, mono: true },
            { label: 'Total cycles', value: state.uptime.totalCycles.toLocaleString(), mono: true },
            { label: 'Cost today', value: `$${state.costToday.toFixed(2)}`, mono: true },
            { label: 'Visitors today', value: state.visitors.today, mono: true },
          ].map((stat, i) => (
            <div key={i} style={{ background: '#0f0f0f', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase', fontFamily: "'JetBrains Mono', monospace" }}>
                {stat.label}
              </span>
              <span style={{
                fontSize: stat.mono ? 20 : 24, fontWeight: 300, color: '#e0e0e0',
                fontFamily: stat.mono ? "'JetBrains Mono', monospace" : "'Crimson Pro', serif",
              }}>
                {stat.value}
              </span>
            </div>
          ))}
        </div>

        {/* Main Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 32 }}>

          {/* Left: Current State */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* Monologue */}
            <div style={{
              background: '#0f0f0f', borderRadius: 8, padding: 24, border: '1px solid #ffffff08',
              animation: 'fadeIn 1s ease, monologueGlow 4s ease-in-out infinite',
            }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 12,
              }}>
                ◈ Inner Monologue
              </div>
              <p style={{ fontSize: 15, lineHeight: 1.65, color: '#c8c0b8', fontStyle: 'italic', fontWeight: 300 }}>
                {state.monologue ? `"${state.monologue}"` : '...'}
              </p>
              <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace" }}>
                  expression: {state.expression}
                </span>
                <span style={{ color: '#333' }}>·</span>
                <span style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace" }}>
                  gaze: {state.gaze}
                </span>
                <span style={{ color: '#333' }}>·</span>
                <span style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace" }}>
                  body: {state.bodyState}
                </span>
              </div>
            </div>

            {/* Drives */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1.2s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 16,
                display: 'flex', justifyContent: 'space-between',
              }}>
                <span>◉ Drive System</span>
                <span style={{ color: '#333', textTransform: 'none', letterSpacing: '0' }}>
                  7 drives · updated each cycle
                </span>
              </div>
              {Object.entries(state.drives).map(([key, val]) => (
                <div
                  key={key}
                  onMouseEnter={() => setHoveredDrive(key)}
                  onMouseLeave={() => setHoveredDrive(null)}
                  style={{ cursor: 'default' }}
                >
                  <DriveBar name={key} value={val} meta={DRIVE_META[key]} />
                </div>
              ))}
              {hoveredDrive && DRIVE_META[hoveredDrive] && (
                <div style={{
                  marginTop: 8, padding: '8px 12px', background: '#1a1a1a', borderRadius: 4,
                  fontSize: 11, color: '#888', fontFamily: "'JetBrains Mono', monospace",
                }}>
                  {DRIVE_META[hoveredDrive].desc}
                </div>
              )}
            </div>

            {/* Threads */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1.4s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 16,
              }}>
                ✧ Active Threads — things on her mind
              </div>
              {state.threads.length === 0 && (
                <div style={{ fontSize: 12, color: '#444', fontStyle: 'italic' }}>No active threads</div>
              )}
              {state.threads.map((t, i) => (
                <div key={i} style={{
                  padding: '10px 0',
                  borderBottom: i < state.threads.length - 1 ? '1px solid #ffffff06' : 'none',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <div>
                    <span style={{ fontSize: 13, color: '#c8c0b8' }}>{t.title}</span>
                    <span style={{
                      marginLeft: 8, fontSize: 9, color: '#555', background: '#ffffff08',
                      padding: '1px 6px', borderRadius: 3, fontFamily: "'JetBrains Mono', monospace",
                    }}>
                      {t.type}
                    </span>
                  </div>
                  <span style={{ fontSize: 10, color: '#444', fontFamily: "'JetBrains Mono', monospace" }}>
                    {t.age}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Activity & Memory */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* Recent Actions */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 12,
              }}>
                ▸ Recent Decisions
              </div>
              <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                {state.recentActions.length === 0 && (
                  <div style={{ fontSize: 12, color: '#444', fontStyle: 'italic' }}>No recent actions</div>
                )}
                {state.recentActions.map((a, i) => (
                  <ActionItem key={i} action={a} />
                ))}
              </div>
            </div>

            {/* Memory Stats */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1.2s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 16,
              }}>
                ◐ Memory — what she carries
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {[
                  { label: 'Visitor Impressions', value: state.memory.totalImpressions, color: '#e8927c' },
                  { label: 'Trait Observations', value: state.memory.totalTraits, color: '#7cc4e8' },
                  { label: 'Totems', value: state.memory.totems, color: '#e8d07c' },
                  { label: 'Self-Discoveries', value: state.memory.selfDiscoveries, color: '#7ce8a3' },
                  { label: 'Journal Entries', value: state.memory.journals, color: '#c49ee8' },
                  { label: 'Returning Visitors', value: state.visitors.returning, color: '#e87c9e' },
                ].map((m, i) => (
                  <div key={i} style={{ padding: '12px', background: '#141414', borderRadius: 6 }}>
                    <div style={{
                      fontSize: 22, fontWeight: 300, color: m.color,
                      fontFamily: "'JetBrains Mono', monospace", marginBottom: 2,
                    }}>
                      {m.value}
                    </div>
                    <div style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace" }}>
                      {m.label}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Last Sleep */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1.4s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 16,
              }}>
                ◌ Last Sleep · {state.lastSleep.hoursAgo}h ago
              </div>
              <div style={{ display: 'flex', gap: 24 }}>
                <div>
                  <div style={{
                    fontSize: 28, fontWeight: 300, color: '#8b9dc3',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {Math.round(state.lastSleep.quality * 100)}%
                  </div>
                  <div style={{ fontSize: 10, color: '#555', fontFamily: "'JetBrains Mono', monospace" }}>
                    Sleep quality
                  </div>
                </div>
                <div style={{ borderLeft: '1px solid #ffffff08', paddingLeft: 24, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ fontSize: 12, color: '#888' }}>
                    <span style={{ color: '#c49ee8' }}>{state.lastSleep.dreamsConsolidated}</span> experiences consolidated
                  </div>
                  <div style={{ fontSize: 12, color: '#888' }}>
                    <span style={{ color: '#7ce8a3' }}>{state.lastSleep.memoriesStrengthened}</span> memories strengthened
                  </div>
                </div>
              </div>
            </div>

            {/* Learned Inhibitions */}
            <div style={{ background: '#0f0f0f', borderRadius: 8, padding: 24, animation: 'fadeIn 1.6s ease' }}>
              <div style={{
                fontSize: 10, color: '#555', letterSpacing: '0.1em', textTransform: 'uppercase',
                fontFamily: "'JetBrains Mono', monospace", marginBottom: 12,
              }}>
                ✕ Learned Inhibitions — things she stopped doing
              </div>
              {state.inhibitions.length === 0 && (
                <div style={{ fontSize: 12, color: '#444', fontStyle: 'italic' }}>None yet</div>
              )}
              {state.inhibitions.map((inh, i) => (
                <div key={i} style={{
                  fontSize: 12, color: '#888', padding: '6px 0',
                  borderBottom: i < state.inhibitions.length - 1 ? '1px solid #ffffff06' : 'none',
                }}>
                  {inh}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '24px 0', borderTop: '1px solid #ffffff06', animation: 'fadeIn 1.8s ease',
        }}>
          <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
            {[
              'Single LLM call per cycle',
              'Sleep-based memory consolidation',
              '7 endogenous drives',
              'Autonomous decision-making',
            ].map((tag, i) => (
              <span key={i} style={{
                fontSize: 9, color: '#444', letterSpacing: '0.08em',
                fontFamily: "'JetBrains Mono', monospace", textTransform: 'uppercase',
              }}>
                {tag}
              </span>
            ))}
          </div>
          <div style={{ fontSize: 10, color: '#333', fontFamily: "'JetBrains Mono', monospace" }}>
            KAI Inc. · Tokyo · shopkeeper.tokyo
          </div>
        </footer>

        {/* Enter the shop CTA */}
        <div style={{ textAlign: 'center', paddingTop: 16, paddingBottom: 40, animation: 'fadeIn 2s ease' }}>
          <a
            href="https://shopkeeper.tokyo"
            style={{
              display: 'inline-block', fontSize: 13, color: '#888', letterSpacing: '0.12em',
              textDecoration: 'none', padding: '12px 32px', border: '1px solid #ffffff12',
              borderRadius: 4, transition: 'all 0.3s ease', fontFamily: "'Crimson Pro', serif",
            }}
            onMouseEnter={(e) => { (e.target as HTMLElement).style.borderColor = '#ffffff30'; (e.target as HTMLElement).style.color = '#ccc'; }}
            onMouseLeave={(e) => { (e.target as HTMLElement).style.borderColor = '#ffffff12'; (e.target as HTMLElement).style.color = '#888'; }}
          >
            Enter the shop →
          </a>
        </div>
      </div>
    </div>
  );
}
