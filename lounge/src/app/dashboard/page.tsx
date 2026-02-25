"use client";

import { useEffect, useState } from "react";
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
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
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

  return (
    <div className="p-5 bg-[#12121a] border border-[#1e1e1a] rounded-lg hover:border-[#d4a574]/30 transition-colors">
      <div className="flex items-center gap-3 mb-3">
        <div className="relative">
          <div className={`w-2 h-2 rounded-full ${status.dot}`} />
          {status.pulse && (
            <div className={`absolute inset-0 w-2 h-2 rounded-full ${status.dot} animate-ping opacity-40`} />
          )}
        </div>
        <h3 className="font-medium">{agent.name || "Unnamed"}</h3>
      </div>
      <p className="text-xs text-[#737373] mb-4">{status.label}</p>
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
  );
}
