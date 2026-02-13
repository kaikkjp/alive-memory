'use client';

import type { WindowState } from '@/lib/types';

interface StatePanelProps {
  state: WindowState | null;
  activityLabel: string;
}

/**
 * Atmospheric sidebar showing weather, time, active threads, and activity.
 * No metrics — everything reads as diegetic narrative.
 */
export default function StatePanel({ state, activityLabel }: StatePanelProps) {
  if (!state) {
    return (
      <aside className="state-panel">
        <p className="state-panel__placeholder">Waiting for connection...</p>
      </aside>
    );
  }

  return (
    <aside className="state-panel">
      {/* Weather as diegetic description */}
      <section className="state-panel__section">
        <p className="state-panel__weather">{state.weather_diegetic}</p>
      </section>

      {/* Time as single word */}
      <section className="state-panel__section">
        <p className="state-panel__time">{state.time_label}</p>
      </section>

      {/* Status */}
      <section className="state-panel__section">
        <p className="state-panel__status">
          {state.status === 'sleeping'
            ? 'She is sleeping.'
            : state.status === 'resting'
              ? 'She is resting.'
              : activityLabel || 'She is here.'}
        </p>
      </section>

      {/* Active threads as a quiet list */}
      {state.threads.length > 0 && (
        <section className="state-panel__section">
          <h3 className="state-panel__heading">Threads</h3>
          <ul className="state-panel__threads">
            {state.threads.map((thread) => (
              <li key={thread.id} className="state-panel__thread">
                <span className="state-panel__thread-title">{thread.title}</span>
                <span className="state-panel__thread-status">{thread.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Visitor indicator */}
      {state.visitor_present && (
        <section className="state-panel__section">
          <p className="state-panel__visitor">A visitor is here.</p>
        </section>
      )}
    </aside>
  );
}
