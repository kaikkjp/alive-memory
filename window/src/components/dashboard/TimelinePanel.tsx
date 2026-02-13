'use client';

import { useState, useEffect } from 'react';

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
      const res = await fetch('http://localhost:8080/api/dashboard/timeline');
      const data = await res.json();
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
    return 'border-neutral-600';
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
                {new Date(event.ts).toLocaleTimeString()}
              </span>
              <span className="text-sm text-neutral-400 font-mono">
                {event.event_type}
              </span>
            </div>
            <div className="text-xs text-neutral-600 font-mono">
              {event.source}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
