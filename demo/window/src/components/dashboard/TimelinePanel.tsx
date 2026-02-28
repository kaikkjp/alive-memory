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

// TODO [TASK-030]: event.payload is fetched but not displayed — add expandable detail view
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
    // Strip common prefixes then humanize snake_case
    const label = type
      .replace(/^action_/, '')
      .replace(/^internal_/, '')
      .replace(/^ambient_/, '')
      .replace(/_/g, ' ');
    return label;
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
        {events.map((event) => (
          <div key={event.id} className={`border-l-2 ${getEventColor(event.event_type)} pl-3`}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-neutral-500 font-mono">
                {formatTs(event.ts)}
              </span>
              <span className="text-sm text-neutral-400 font-mono">
                {formatEventType(event.event_type)}
              </span>
            </div>
            {event.source && (
              <div className="text-xs text-neutral-600 font-mono truncate">
                {formatSource(event.source)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
