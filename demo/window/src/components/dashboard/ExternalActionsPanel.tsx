'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { ExternalActionsData, ChannelStatus, ExternalRateLimitStatus } from '@/lib/types';

function ChannelToggle({ ch, onToggle }: {
  ch: ChannelStatus;
  onToggle: (channel: string, enabled: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between text-xs font-mono">
      <span className="text-neutral-300">{ch.channel}</span>
      <button
        onClick={() => onToggle(ch.channel, !ch.enabled)}
        className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
          ch.enabled
            ? 'bg-emerald-900 text-emerald-300 hover:bg-emerald-800'
            : 'bg-neutral-800 text-neutral-500 hover:bg-neutral-700'
        }`}
      >
        {ch.enabled ? 'ON' : 'OFF'}
      </button>
    </div>
  );
}

function RateLimitRow({ rl }: { rl: ExternalRateLimitStatus }) {
  const hourlyPct = rl.hourly_limit > 0 ? (rl.hourly_used / rl.hourly_limit) * 100 : 0;
  const dailyPct = rl.daily_limit > 0 ? (rl.daily_used / rl.daily_limit) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-neutral-300">{rl.action}</span>
        <div className="flex items-center gap-2 text-neutral-500">
          {rl.cooldown_remaining > 0 && (
            <span className="text-yellow-500">{rl.cooldown_remaining}s</span>
          )}
        </div>
      </div>
      <div className="flex gap-2">
        <div className="flex-1">
          <div className="h-1 bg-neutral-800 rounded overflow-hidden">
            <div
              className={`h-full transition-all ${hourlyPct > 80 ? 'bg-red-500' : hourlyPct > 50 ? 'bg-yellow-500' : 'bg-emerald-600'}`}
              style={{ width: `${Math.min(hourlyPct, 100)}%` }}
            />
          </div>
          <div className="text-[10px] text-neutral-600 font-mono mt-0.5">
            {rl.hourly_used}/{rl.hourly_limit}/hr
          </div>
        </div>
        <div className="flex-1">
          <div className="h-1 bg-neutral-800 rounded overflow-hidden">
            <div
              className={`h-full transition-all ${dailyPct > 80 ? 'bg-red-500' : dailyPct > 50 ? 'bg-yellow-500' : 'bg-emerald-600'}`}
              style={{ width: `${Math.min(dailyPct, 100)}%` }}
            />
          </div>
          <div className="text-[10px] text-neutral-600 font-mono mt-0.5">
            {rl.daily_used}/{rl.daily_limit}/day
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ExternalActionsPanel() {
  const [data, setData] = useState<ExternalActionsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getExternalActions();
      setData(result);
    } catch (err) {
      console.error('[ExternalActionsPanel] Failed to fetch:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleToggle = async (channel: string, enabled: boolean) => {
    try {
      await dashboardApi.toggleChannel(channel, enabled);
      fetchData();
    } catch (err) {
      console.error('[ExternalActionsPanel] Toggle failed:', err);
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">External Actions</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">External Actions</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">External Actions</h2>

      {/* Channel kill switches */}
      <div className="mb-4">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Channels</h3>
        <div className="space-y-1.5">
          {data.channels.map((ch) => (
            <ChannelToggle key={ch.channel} ch={ch} onToggle={handleToggle} />
          ))}
        </div>
      </div>

      {/* Rate limits */}
      <div className="mb-4">
        <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Rate Limits</h3>
        <div className="space-y-3">
          {data.rate_limits.map((rl) => (
            <RateLimitRow key={rl.action} rl={rl} />
          ))}
        </div>
      </div>

      {/* Recent log */}
      {data.recent_log.length > 0 && (
        <div>
          <h3 className="text-xs font-mono text-neutral-500 uppercase mb-2">Recent</h3>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {data.recent_log.slice(0, 8).map((entry, i) => (
              <div key={i} className="flex items-center justify-between text-[10px] font-mono">
                <div className="flex items-center gap-1.5">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${entry.success ? 'bg-emerald-500' : 'bg-red-500'}`} />
                  <span className="text-neutral-400">{entry.action}</span>
                </div>
                <span className="text-neutral-600">
                  {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
