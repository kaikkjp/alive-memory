"use client";

function formatRelativeTime(timestamp: string): string {
  try {
    const diff = Date.now() - new Date(timestamp).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "now";
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `${days}d`;
  } catch {
    return "";
  }
}

function humanize(action: string): string {
  return action.replace(/_/g, " ");
}

interface ActionsLogProps {
  actions: Array<{ action: string; timestamp: string; content?: string }>;
}

export default function ActionsLog({ actions }: ActionsLogProps) {
  if (actions.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic px-3">
        No recent actions
      </p>
    );
  }

  return (
    <div className="space-y-1.5 px-3">
      {actions.map((a, i) => (
        <div key={`${a.timestamp}-${i}`} className="flex items-baseline gap-2">
          <span className="text-[10px] text-[#525252] shrink-0 w-6 text-right">
            {formatRelativeTime(a.timestamp)}
          </span>
          <span className="text-xs text-[#a3a3a3] truncate">
            {humanize(a.action)}
          </span>
        </div>
      ))}
    </div>
  );
}
