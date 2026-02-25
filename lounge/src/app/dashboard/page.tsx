"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { Agent } from "@/lib/types";
import CreateAgentWizard from "@/components/CreateAgentWizard";

export default function DashboardPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-[#737373]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Your Agents</h1>
          <p className="text-[#737373] text-sm mt-1">
            {agents.length} agent{agents.length !== 1 ? "s" : ""}
          </p>
        </div>
        <button
          onClick={() => setShowWizard(true)}
          className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
        >
          Create Agent
        </button>
      </div>

      {showWizard && (
        <CreateAgentWizard
          onCreated={handleAgentCreated}
          onCancel={() => setShowWizard(false)}
        />
      )}

      {agents.length === 0 && !showWizard ? (
        <div className="text-center py-16">
          <p className="text-[#737373] mb-4">No agents yet</p>
          <button
            onClick={() => setShowWizard(true)}
            className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
          >
            Create Your First Agent
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
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const statusColor =
    agent.status === "running"
      ? "bg-[#22c55e]"
      : agent.status === "error"
        ? "bg-[#ef4444]"
        : "bg-[#737373]";

  return (
    <Link
      href={`/agent/${agent.id}/lounge`}
      className="block p-5 bg-[#141414] border border-[#262626] rounded-lg hover:border-[#3b82f6]/50 transition-colors"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        <h3 className="font-semibold">{agent.name}</h3>
      </div>
      <div className="flex gap-4 text-xs text-[#737373]">
        <span>{agent.status}</span>
        <span>port {agent.port}</span>
      </div>
    </Link>
  );
}
