"use client";

import { use } from "react";
import AgentNav from "@/components/AgentNav";
import McpServersPanel from "@/components/mcp/McpServersPanel";

export default function ToolsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="tools" />
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          <McpServersPanel agentId={id} />
        </div>
      </div>
    </div>
  );
}
