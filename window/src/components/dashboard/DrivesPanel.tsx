'use client';

import { useState, useEffect } from 'react';

interface Drives {
  social_hunger: number;
  curiosity: number;
  expression_need: number;
  rest_need: number;
  energy: number;
  mood_valence: number;
  mood_arousal: number;
  updated_at: string | null;
}

export default function DrivesPanel() {
  const [drives, setDrives] = useState<Drives | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDrives = async () => {
    try {
      const res = await fetch('http://localhost:8080/api/dashboard/drives');
      const data = await res.json();
      setDrives(data);
    } catch (err) {
      console.error('Failed to fetch drives:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDrives();
    const interval = setInterval(fetchDrives, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, []);

  const DriveBar = ({ label, value, color }: { label: string; value: number; color: string }) => {
    const percentage = Math.round(value * 100);
    return (
      <div>
        <div className="flex justify-between text-xs text-neutral-400 font-mono mb-1">
          <span>{label}</span>
          <span>{percentage}%</span>
        </div>
        <div className="h-2 bg-neutral-800 rounded overflow-hidden">
          <div
            className={`h-full ${color} transition-all duration-500`}
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Drives</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!drives) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Drives</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Drives</h2>
      <div className="space-y-3">
        <DriveBar label="Social Hunger" value={drives.social_hunger} color="bg-blue-500" />
        <DriveBar label="Curiosity" value={drives.curiosity} color="bg-purple-500" />
        <DriveBar label="Expression Need" value={drives.expression_need} color="bg-pink-500" />
        <DriveBar label="Rest Need" value={drives.rest_need} color="bg-indigo-500" />
        <DriveBar label="Energy" value={drives.energy} color="bg-emerald-500" />
        <div className="pt-3 border-t border-neutral-700">
          <DriveBar
            label="Mood Valence"
            value={(drives.mood_valence + 1) / 2}
            color="bg-amber-500"
          />
          <div className="mt-2">
            <DriveBar
              label="Mood Arousal"
              value={(drives.mood_arousal + 1) / 2}
              color="bg-rose-500"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
