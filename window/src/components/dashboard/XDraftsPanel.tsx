'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/dashboard-api';
import type { XDraftsData, XDraft } from '@/lib/types';

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-amber-400',
  approved: 'text-blue-400',
  rejected: 'text-neutral-500',
  posted: 'text-emerald-400',
  failed: 'text-red-400',
};

export default function XDraftsPanel() {
  const [data, setData] = useState<XDraftsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const result = await dashboardApi.getXDrafts();
      setData(result);
    } catch (err) {
      console.error('[XDraftsPanel] Failed to fetch:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleApprove = async (draftId: string, autoPost: boolean) => {
    setActing(draftId);
    try {
      await dashboardApi.approveXDraft(draftId, autoPost);
      await fetchData();
    } catch (err) {
      console.error('[XDraftsPanel] Approve failed:', err);
    } finally {
      setActing(null);
    }
  };

  const handleReject = async (draftId: string) => {
    setActing(draftId);
    try {
      await dashboardApi.rejectXDraft(draftId);
      await fetchData();
    } catch (err) {
      console.error('[XDraftsPanel] Reject failed:', err);
    } finally {
      setActing(null);
    }
  };

  if (loading) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">X Drafts</h2>
        <p className="text-sm text-neutral-500 font-mono">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
        <h2 className="text-lg font-mono text-neutral-300 mb-4">X Drafts</h2>
        <p className="text-sm text-red-400 font-mono">Error loading data</p>
      </div>
    );
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-mono text-neutral-300">X Drafts</h2>
        {data.pending_count > 0 && (
          <span className="px-2 py-0.5 bg-amber-900 text-amber-300 text-xs font-mono rounded">
            {data.pending_count} pending
          </span>
        )}
      </div>

      {data.drafts.length === 0 ? (
        <p className="text-xs text-neutral-600 font-mono">No drafts yet</p>
      ) : (
        <div className="space-y-3 max-h-96 overflow-y-auto">
          {data.drafts.map((draft: XDraft) => (
            <div key={draft.id} className="border border-neutral-800 rounded p-3">
              <div className="flex items-center justify-between mb-2">
                <span className={`text-xs font-mono ${STATUS_COLORS[draft.status] || 'text-neutral-400'}`}>
                  {draft.status}
                </span>
                <span className="text-xs text-neutral-600 font-mono">
                  {timeAgo(draft.created_at)}
                </span>
              </div>
              <p className="text-sm text-neutral-200 font-mono mb-2 whitespace-pre-wrap break-words">
                {draft.draft_text}
              </p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-600 font-mono">
                  {draft.draft_text.length}/280
                </span>
                {draft.status === 'pending' && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApprove(draft.id, false)}
                      disabled={acting === draft.id}
                      className="px-2 py-1 text-xs font-mono bg-neutral-700 hover:bg-neutral-600 text-neutral-200 rounded disabled:opacity-50"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleApprove(draft.id, true)}
                      disabled={acting === draft.id}
                      className="px-2 py-1 text-xs font-mono bg-emerald-900 hover:bg-emerald-800 text-emerald-200 rounded disabled:opacity-50"
                    >
                      Approve + Post
                    </button>
                    <button
                      onClick={() => handleReject(draft.id)}
                      disabled={acting === draft.id}
                      className="px-2 py-1 text-xs font-mono bg-neutral-800 hover:bg-neutral-700 text-neutral-400 rounded disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                )}
                {draft.status === 'posted' && draft.x_post_id && (
                  <a
                    href={`https://x.com/i/status/${draft.x_post_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 font-mono"
                  >
                    View on X
                  </a>
                )}
                {draft.status === 'failed' && draft.error_message && (
                  <span className="text-xs text-red-400 font-mono truncate max-w-48" title={draft.error_message}>
                    {draft.error_message}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
