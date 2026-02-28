"use client";

import Link from "next/link";

const tabs = [
  { key: "lounge", label: "Lounge", href: (id: string) => `/agent/${id}/lounge` },
  { key: "configure", label: "Configure", href: (id: string) => `/agent/${id}/configure` },
  { key: "tools", label: "Tools", href: (id: string) => `/agent/${id}/tools` },
  { key: "api-keys", label: "API Keys", href: (id: string) => `/agent/${id}/api-keys` },
  { key: "docs", label: "Docs", href: (id: string) => `/agent/${id}/docs` },
];

export default function AgentNav({
  agentId,
  active,
}: {
  agentId: string;
  active: string;
}) {
  return (
    <nav className="border-b border-[#1e1e1a] px-4">
      <div className="max-w-5xl mx-auto flex items-center gap-6 h-12">
        <Link
          href="/dashboard"
          className="text-[#737373] hover:text-white text-sm transition-colors mr-4"
        >
          &larr; Agents
        </Link>
        {tabs.map((tab) => (
          <Link
            key={tab.key}
            href={tab.href(agentId)}
            className={`text-sm py-3 border-b-2 transition-colors ${
              active === tab.key
                ? "border-[#d4a574] text-white"
                : "border-transparent text-[#737373] hover:text-white"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
