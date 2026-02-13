'use client';

import { useState, useEffect } from 'react';

interface CollectionItem {
  id: string;
  title: string;
  item_type: string;
  location: string;
  origin: string;
  her_feeling: string | null;
  created_at: string | null;
}

export default function CollectionPanel() {
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchCollection = async () => {
    try {
      const res = await fetch('http://localhost:8080/api/dashboard/collection');
      const data = await res.json();
      setItems(data.collection || []);
    } catch (err) {
      console.error('Failed to fetch collection:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCollection();
    const interval = setInterval(fetchCollection, 20000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">Collection</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <h2 className="text-lg font-mono text-neutral-300 mb-4">Collection</h2>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {items.length === 0 && (
          <p className="text-sm text-neutral-500 font-mono">Collection empty</p>
        )}
        {items.map((item) => (
          <div key={item.id} className="border-l-2 border-emerald-500 pl-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm text-emerald-400 font-mono font-bold">
                {item.title}
              </span>
              <span className="text-xs text-neutral-500 font-mono">
                {item.item_type}
              </span>
            </div>
            {item.her_feeling && (
              <div className="text-xs text-neutral-400 font-mono italic">
                {item.her_feeling}
              </div>
            )}
            <div className="text-xs text-neutral-600 font-mono mt-1">
              {item.location} • {item.origin}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
