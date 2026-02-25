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
  const menuRef = useRef<HTMLDivElement>(null);

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

  async function handleStop() {
    setActionLoading(true);
    setMenuOpen(false);
    try {
      await fetch(`/api/agents/${agent.id}/stop`, { method: "POST" });
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleStart() {
    setActionLoading(true);
    setMenuOpen(false);
    try {
      await fetch(`/api/agents/${agent.id}/start`, { method: "POST" });
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRestart() {
    setActionLoading(true);
    setMenuOpen(false);
    try {
      await fetch(`/api/agents/${agent.id}/stop`, { method: "POST" });
      await new Promise((r) => setTimeout(r, 1000));
      await fetch(`/api/agents/${agent.id}/start`, { method: "POST" });
      onRefresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDelete() {
    setActionLoading(true);
    setDeleteConfirm(false);
    setMenuOpen(false);
    try {
      await fetch(`/api/agents/${agent.id}`, { method: "DELETE" });
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

        {/* Status + cycles */}
        <p className="text-xs text-[#737373] mb-1 ml-5">{status.label}</p>
        <p className="text-xs text-[#525252] mb-4 ml-5">{cycleText}</p>

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
