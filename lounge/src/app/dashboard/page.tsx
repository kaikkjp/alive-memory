"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Agent } from "@/lib/types";
import CreateAgentWizard from "@/components/CreateAgentWizard";

export default function DashboardPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);
  const router = useRouter();

  useEffect(() => {
    fetchAgents();
  }, []);

  async function fetchAgents() {
    try {
      const res = await fetch("/api/agents");
      if (res.ok) {
        const data = await res.json();
        setAgents(data.agents);
      }
    } finally {
      setLoading(false);
    }
  }

  function handleAgentCreated() {
    setShowWizard(false);
    fetchAgents();
  }

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-[#737373] text-sm">Loading...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <nav className="border-b border-[#1e1e1a] px-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between h-14">
          <span className="text-sm font-light tracking-[0.15em] uppercase text-[#9a8c7a]">
            ALIVE
          </span>
          <button
            onClick={handleLogout}
            className="text-xs text-[#737373] hover:text-[#a3a3a3] transition-colors"
          >
            Logout
          </button>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-semibold">Your Agents</h1>
            <p className="text-[#737373] text-sm mt-1">
              {agents.length} agent{agents.length !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
          >
            Bring a new one to life
          </button>
        </div>

        {showWizard && (
          <CreateAgentWizard
            onCreated={handleAgentCreated}
            onCancel={() => setShowWizard(false)}
          />
        )}

        {agents.length === 0 && !showWizard ? (
          <div className="text-center py-20">
            <p className="text-[#737373] mb-1">No agents yet</p>
            <p className="text-[#525252] text-sm mb-6">
              Bring a digital lifeform into existence.
            </p>
            <button
              onClick={() => setShowWizard(true)}
              className="px-5 py-2.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
            >
              Bring a new one to life
            </button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onRefresh={fetchAgents}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface LiveState {
  mood?: { valence: number; arousal: number };
  energy?: number;
  drives?: {
    curiosity: number;
    social_hunger: number;
    expression_need: number;
  };
  engagement_state?: string;
  current_action?: string | null;
  is_sleeping?: boolean;
  inner_voice?: string | null;
}

function getMoodWord(valence: number, arousal: number): string {
  if (valence > 0.3 && arousal > 0.3) return "excited";
  if (valence > 0.3 && arousal < -0.1) return "serene";
  if (valence > 0.1) return "content";
  if (valence < -0.3 && arousal > 0.3) return "agitated";
  if (valence < -0.3) return "melancholic";
  if (valence < -0.1) return "pensive";
  if (arousal > 0.3) return "alert";
  if (arousal < -0.2) return "drowsy";
  return "neutral";
}

function getMoodColor(valence: number): string {
  if (valence > 0.2) return "#d4a574";
  if (valence < -0.2) return "#8b9dc3";
  return "#9a8c7a";
}

function CardDriveBar({ value, color }: { value: number; color: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex-1 h-[3px] rounded-full bg-[#161616] overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-[2s] ease-out"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  );
}

function AgentCard({
  agent,
  onRefresh,
}: {
  agent: Agent;
  onRefresh: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [live, setLive] = useState<LiveState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Poll live status when running
  useEffect(() => {
    if (agent.status !== "running") {
      setLive(null);
      return;
    }
    let mounted = true;
    async function poll() {
      try {
        const res = await fetch(`/api/agents/${agent.id}/status`);
        if (!res.ok || !mounted) return;
        const data = await res.json();
        if (data.status === "offline" || !mounted) return;
        const drives = data.drives;
        setLive({
          mood: data.mood,
          energy: data.energy ?? drives?.energy,
          drives: drives
            ? {
                curiosity: typeof drives.curiosity === "number" ? drives.curiosity : drives.curiosity?.value ?? 0.45,
                social_hunger: typeof drives.social_hunger === "number" ? drives.social_hunger : drives.social_hunger?.value ?? 0.5,
                expression_need: typeof drives.expression_need === "number" ? drives.expression_need : drives.expression_need?.value ?? 0.4,
              }
            : undefined,
          engagement_state: data.engagement_state,
          current_action: data.current_action,
          is_sleeping: data.is_sleeping,
          inner_voice: data.inner_voice,
        });
      } catch {
        // silent
      }
    }
    poll();
    const timer = setInterval(poll, 30_000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [agent.id, agent.status]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  const statusConfig = {
    running: {
      dot: "bg-[#d4a574]",
      pulse: true,
      label: "Thinking quietly",
    },
    stopped: {
      dot: "bg-[#525252]",
      pulse: false,
      label: "Stopped",
    },
    error: {
      dot: "bg-[#ef4444]",
      pulse: false,
      label: "Something went wrong",
    },
  };

  const status = statusConfig[agent.status] || statusConfig.stopped;
  const isRunning = agent.status === "running";

  const [actionError, setActionError] = useState<string | null>(null);

  async function handleStop() {
    setActionLoading(true);
    setMenuOpen(false);
    setActionError(null);
    try {
      const res = await fetch(`/api/agents/${agent.id}/stop`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionError(body.error || "Failed to stop");
      }
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleStart() {
    setActionLoading(true);
    setMenuOpen(false);
    setActionError(null);
    try {
      const res = await fetch(`/api/agents/${agent.id}/start`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionError(body.error || "Failed to start");
      }
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRestart() {
    setActionLoading(true);
    setMenuOpen(false);
    setActionError(null);
    try {
      const stopRes = await fetch(`/api/agents/${agent.id}/stop`, { method: "POST" });
      if (!stopRes.ok) {
        const body = await stopRes.json().catch(() => ({}));
        setActionError(body.error || "Failed to stop");
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
      const startRes = await fetch(`/api/agents/${agent.id}/start`, { method: "POST" });
      if (!startRes.ok) {
        const body = await startRes.json().catch(() => ({}));
        setActionError(body.error || "Failed to restart");
      }
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDelete() {
    setActionLoading(true);
    setDeleteConfirm(false);
    setMenuOpen(false);
    setActionError(null);
    try {
      const res = await fetch(`/api/agents/${agent.id}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setActionError(body.error || "Failed to delete");
      }
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  const cycleText =
    agent.cycle_count != null && agent.cycle_count > 0
      ? `Alive for ${agent.cycle_count.toLocaleString()} cycles`
      : "Not yet awakened";

  return (
    <>
      <div
        className={`p-5 bg-[#12121a] border border-[#1e1e1a] rounded-lg hover:border-[#d4a574]/30 transition-all hover:-translate-y-0.5 ${
          actionLoading ? "opacity-60 pointer-events-none" : ""
        }`}
      >
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-3">
            <div className="relative mt-1">
              <div className={`w-2 h-2 rounded-full ${status.dot}`} />
              {status.pulse && (
                <div
                  className={`absolute inset-0 w-2 h-2 rounded-full ${status.dot} animate-ping opacity-40`}
                />
              )}
            </div>
            <h3 className="font-medium">{agent.name || "Unnamed"}</h3>
          </div>

          {/* ⋯ menu */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-1 text-[#525252] hover:text-[#a3a3a3] transition-colors text-lg leading-none"
              title="Actions"
            >
              ⋯
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-8 w-40 bg-[#1a1a1a] border border-[#262620] rounded-lg shadow-xl py-1 z-20">
                {isRunning ? (
                  <>
                    <MenuBtn onClick={handleRestart}>Restart</MenuBtn>
                    <MenuBtn onClick={handleStop}>Stop</MenuBtn>
                  </>
                ) : (
                  <MenuBtn onClick={handleStart}>Start</MenuBtn>
                )}
                <div className="border-t border-[#262620] my-1" />
                <MenuBtn
                  onClick={() => {
                    setMenuOpen(false);
                    setDeleteConfirm(true);
                  }}
                  danger
                >
                  Delete
                </MenuBtn>
              </div>
            )}
          </div>
        </div>

        {/* Role subtitle */}
        {agent.role && (
          <p className="text-xs text-[#9a8c7a] mb-2 ml-5">{agent.role}</p>
        )}

        {/* Status + live vitals */}
        {live && live.mood ? (
          <div className="ml-5 mb-4 space-y-1.5">
            {/* Mood + energy */}
            <div className="flex items-center gap-2 text-xs">
              <span
                className="font-medium"
                style={{ color: getMoodColor(live.mood.valence) }}
              >
                {getMoodWord(live.mood.valence, live.mood.arousal)}
              </span>
              <div className="w-16 h-1 rounded-full bg-[#161616] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-1000 ease-out"
                  style={{
                    width: `${Math.round(Math.max(0, Math.min(1, live.energy ?? 0.5)) * 100)}%`,
                    backgroundColor: getMoodColor(live.mood.valence),
                  }}
                />
              </div>
              <span className="text-[#525252]">
                {live.is_sleeping
                  ? "sleeping"
                  : live.current_action
                    ? live.current_action.replace(/_/g, " ")
                    : live.engagement_state === "engaged"
                      ? "talking"
                      : "idle"}
              </span>
            </div>
            {/* Drive bars */}
            {live.drives && (
              <div className="flex gap-1.5 pr-2">
                <CardDriveBar value={live.drives.curiosity} color="#7ab8b8" />
                <CardDriveBar value={live.drives.social_hunger} color="#c4869a" />
                <CardDriveBar value={live.drives.expression_need} color="#9a8cc4" />
              </div>
            )}
            {/* Monologue snippet */}
            {live.inner_voice && (
              <p className="text-[10px] text-[#525252] italic truncate leading-tight">
                &ldquo;{typeof live.inner_voice === "string" ? live.inner_voice.slice(0, 80) : ""}&rdquo;
              </p>
            )}
            <p className="text-[10px] text-[#3a3a3a]">{cycleText}</p>
          </div>
        ) : (
          <>
            <p className="text-xs text-[#737373] mb-1 ml-5">{status.label}</p>
            <p className="text-xs text-[#525252] mb-4 ml-5">{cycleText}</p>
          </>
        )}

        {actionError && (
          <p className="text-xs text-red-400 mb-3 ml-5">{actionError}</p>
        )}

        <div className="flex gap-2">
          <Link
            href={`/agent/${agent.id}/lounge`}
            className="flex-1 text-center px-3 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-xs font-medium transition-colors"
          >
            Lounge
          </Link>
          <Link
            href={`/agent/${agent.id}/configure`}
            className="px-3 py-2 border border-[#262620] text-[#a3a3a3] hover:text-white hover:border-[#3a3a34] rounded-lg text-xs transition-colors"
          >
            Configure
          </Link>
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-sm mx-4">
            <h3 className="text-base font-semibold mb-2">
              Delete {agent.name || "this agent"}?
            </h3>
            <p className="text-sm text-[#a3a3a3] mb-4">
              This will permanently destroy the agent, all memories, journals,
              and data. This cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteConfirm(false)}
                className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                className="px-4 py-2 bg-[#ef4444]/80 hover:bg-[#ef4444] text-white rounded-lg text-sm font-medium transition-colors"
              >
                Delete forever
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function MenuBtn({
  onClick,
  children,
  danger,
}: {
  onClick: () => void;
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${
        danger
          ? "text-[#ef4444] hover:bg-[#ef4444]/10"
          : "text-[#a3a3a3] hover:bg-[#262626] hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}
