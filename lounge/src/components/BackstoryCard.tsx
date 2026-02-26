"use client";

import { useState } from "react";

interface BackstoryCardProps {
  sourceId: string;
  text: string;
  date: string;
  onDelete: (sourceId: string) => void;
}

export default function BackstoryCard({
  sourceId,
  text,
  date,
  onDelete,
}: BackstoryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const preview = text.length > 120 ? text.slice(0, 120) + "..." : text;

  function formatDate(ts: string): string {
    try {
      return new Date(ts).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
    } catch {
      return ts;
    }
  }

  return (
    <div className="p-3 bg-[#12121a] border border-[#262620] rounded-lg group">
      <div className="flex justify-between items-start mb-1.5">
        <span className="text-[10px] text-[#525252]">{formatDate(date)}</span>
        {confirming ? (
          <div className="flex gap-1.5">
            <button
              onClick={() => setConfirming(false)}
              className="text-[10px] text-[#525252] hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => onDelete(sourceId)}
              className="text-[10px] text-[#ef4444] hover:text-[#f87171] transition-colors"
            >
              Remove
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="text-[10px] text-[#525252] hover:text-[#ef4444] opacity-0 group-hover:opacity-100 transition-all"
          >
            Remove
          </button>
        )}
      </div>
      <p
        onClick={() => text.length > 120 && setExpanded(!expanded)}
        className={`text-xs text-[#d4d4d4] leading-relaxed ${
          text.length > 120 ? "cursor-pointer" : ""
        }`}
      >
        {expanded ? text : preview}
      </p>
    </div>
  );
}
