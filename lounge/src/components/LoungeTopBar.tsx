"use client";

import Link from "next/link";

interface LoungeTopBarProps {
  agentId: string;
  agentName: string;
  status: "connected" | "reconnecting" | "offline" | "error";
  isSleeping: boolean;
  onRestClick: () => void;
  onBackClick: () => void;
  onSettingsClick: () => void;
  settingsOpen?: boolean;
}

const STATUS_CONFIG = {
  connected: { label: "Awake", className: "bg-[#d4a574] animate-pulse-warm" },
  reconnecting: { label: "Reconnecting", className: "bg-[#d4a574]/50 animate-pulse" },
  offline: { label: "Offline", className: "bg-[#525252]" },
  error: { label: "Error", className: "bg-[#ef4444]" },
} as const;

export default function LoungeTopBar({
  agentId,
  agentName,
  status,
  isSleeping,
  onRestClick,
  onBackClick,
  onSettingsClick,
  settingsOpen,
}: LoungeTopBarProps) {
  const statusCfg = isSleeping && status === "connected"
    ? { label: "Sleeping", className: "bg-[#8b9dc3] animate-pulse-cool" }
    : STATUS_CONFIG[status];

  return (
    <div className={`flex items-center justify-between px-4 py-3 border-b bg-[#0a0a0f]/80 backdrop-blur-sm transition-colors ${
      settingsOpen ? "border-[#d4a574]/20" : "border-[#1e1e1a]"
    }`}>
      <div className="flex items-center gap-3">
        <button
          onClick={onBackClick}
          className="text-[#737373] hover:text-white text-sm transition-colors"
        >
          &larr; Agents
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
        <Link
          href={`/agent/${agentId}/api-keys`}
          className="p-1.5 rounded-md text-sm text-[#525252] hover:text-[#d4a574] transition-colors"
          title="API Keys"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.5 1.5a3 3 0 0 1 0 4.24l-1.26 1.26.5.5-5 5H2.5v-2.24l5-5 .5.5L9.26 4.5a3 3 0 0 1 1.24-3z" />
            <circle cx="11.5" cy="3.5" r="0.5" fill="currentColor" />
          </svg>
        </Link>
        <Link
          href={`/agent/${agentId}/docs`}
          className="p-1.5 rounded-md text-sm text-[#525252] hover:text-[#d4a574] transition-colors"
          title="API Docs"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 2.5h7l3 3V13.5H3z" />
            <path d="M10 2.5v3h3" />
            <path d="M5.5 8h5M5.5 10.5h3" />
          </svg>
        </Link>
        <button
          onClick={onSettingsClick}
          className={`p-1.5 rounded-md text-sm transition-colors ${
            settingsOpen
              ? "text-[#d4a574] bg-[#d4a574]/10"
              : "text-[#525252] hover:text-[#d4a574]"
          }`}
          title="Settings"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="2.5" />
            <path d="M6.5 1.5h3l.4 1.6a5.5 5.5 0 0 1 1.3.8l1.6-.5 1.5 2.6-1.2 1.1a5.5 5.5 0 0 1 0 1.8l1.2 1.1-1.5 2.6-1.6-.5a5.5 5.5 0 0 1-1.3.8l-.4 1.6h-3l-.4-1.6a5.5 5.5 0 0 1-1.3-.8l-1.6.5-1.5-2.6 1.2-1.1a5.5 5.5 0 0 1 0-1.8L1.7 6l1.5-2.6 1.6.5a5.5 5.5 0 0 1 1.3-.8z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
