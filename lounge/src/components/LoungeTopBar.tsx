"use client";

interface LoungeTopBarProps {
  agentName: string;
  status: "connected" | "reconnecting" | "offline" | "error";
  isSleeping: boolean;
  onRestClick: () => void;
  onBackClick: () => void;
}

const STATUS_CONFIG = {
  connected: { label: "Awake", className: "bg-[#d4a574] animate-pulse-warm" },
  reconnecting: { label: "Reconnecting", className: "bg-[#d4a574]/50 animate-pulse" },
  offline: { label: "Offline", className: "bg-[#525252]" },
  error: { label: "Error", className: "bg-[#ef4444]" },
} as const;

export default function LoungeTopBar({
  agentName,
  status,
  isSleeping,
  onRestClick,
  onBackClick,
}: LoungeTopBarProps) {
  const statusCfg = isSleeping && status === "connected"
    ? { label: "Sleeping", className: "bg-[#8b9dc3] animate-pulse-cool" }
    : STATUS_CONFIG[status];

  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e1e1a] bg-[#0a0a0f]/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <button
          onClick={onBackClick}
          className="text-[#737373] hover:text-white text-sm transition-colors"
        >
          &larr; Bay
        </button>
        <span className="text-sm font-medium text-[#e5e5e5] truncate max-w-[200px]">
          {agentName}
        </span>
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${statusCfg.className}`} />
          <span className="text-xs text-[#737373]">{statusCfg.label}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onRestClick}
          disabled={isSleeping || status !== "connected"}
          className="px-3 py-1.5 text-xs rounded-md border border-[#262620] text-[#a3a3a3] hover:text-white hover:border-[#d4a574]/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isSleeping ? "Sleeping..." : "Rest Now"}
        </button>
      </div>
    </div>
  );
}
