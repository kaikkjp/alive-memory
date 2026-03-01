'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';

interface TimelineEvent {
  id: string;
  event_type: string;
  source: string;
  ts: string;
  payload: any;
}

export default function TimelinePanel() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTimeline = async () => {
    try {
      const data = await dashboardApi.getTimeline();
      setEvents(data.timeline || []);
    } catch (err) {
      console.error('Failed to fetch timeline:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTimeline();
    const interval = setInterval(fetchTimeline, 5000);
    return () => clearInterval(interval);
  }, []);

  const getEventColor = (type: string) => {
    if (type.startsWith('visitor_')) return 'border-blue-500';
    if (type.includes('cycle')) return 'border-purple-500';
    if (type.includes('drive')) return 'border-amber-500';
    if (type.startsWith('action_')) return 'border-emerald-600';
    if (type.startsWith('internal_')) return 'border-orange-700';
    if (type.startsWith('ambient_')) return 'border-sky-700';
    if (type === 'content_consumed') return 'border-teal-600';
    return 'border-neutral-600';
  };

  const formatEventType = (type: string) => {
    const label = type
      .replace(/^action_/, '')
      .replace(/^internal_/, '')
      .replace(/^ambient_/, '')
      .replace(/_/g, ' ');
    return label;
  };

  const getEventDetail = (event: TimelineEvent): string | null => {
    const p = event.payload;
    if (!p || typeof p !== 'object') return null;

    switch (event.event_type) {
      case 'action_body': {
        const parts: string[] = [];
        if (p.expression) parts.push(p.expression);
        if (p.body_state) parts.push(p.body_state);
        if (p.gaze) parts.push(`gaze=${p.gaze}`);
        return parts.join(', ') || null;
      }
      case 'action_speak':
        return p.text ? `"${p.text}"` : null;
      case 'ambient_weather':
        return p.description || p.condition || null;
      case 'content_consumed':
        return [p.artist, p.title].filter(Boolean).join(' — ') || p.content_id || null;
      case 'drift_notable':
        return p.composite != null ? `composite=${Number(p.composite).toFixed(3)}` : null;
      case 'internal_conflict':
        return p.description || null;
      case 'internal_shift_candidate':
        return p.trait_key ? `${p.trait_key}: ${p.old_value} → ${p.new_value}` : null;
      default: {
        // For unknown types, show first short string value from payload
        const vals = Object.values(p).filter(v => typeof v === 'string' && v.length > 0 && v.length < 120);
        return (vals[0] as string) || null;
      }
    }
  };

  const formatSource = (source: string) => {
    // visitor:<uuid> → visitor
    if (source.startsWith('visitor:')) return 'visitor';
    return source;
  };

  const formatTs = (ts: string) => {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleTimeString();
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Timeline</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Timeline</h2>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {events.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">No recent events</p>
        )}
        {events.map((event) => {
          const detail = getEventDetail(event);
          return (
            <div key={event.id} className={`border-l-2 ${getEventColor(event.event_type)} pl-3`}>
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-500 font-mono">
                  {formatTs(event.ts)}
                </span>
                <span className="text-sm text-neutral-400 font-mono">
                  {formatEventType(event.event_type)}
                </span>
              </div>
              {detail && (
                <div className="text-xs text-neutral-500 font-mono truncate mt-0.5">
                  {detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
