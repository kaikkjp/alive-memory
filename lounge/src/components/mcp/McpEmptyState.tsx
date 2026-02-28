"use client";

export default function McpEmptyState({ onConnect }: { onConnect: () => void }) {
  return (
    <div className="text-center py-12 px-4">
      <div className="text-3xl mb-3 opacity-60">&#x1F50C;</div>
      <h3 className="text-sm font-medium mb-2">No tools connected</h3>
      <p className="text-xs text-[#737373] max-w-sm mx-auto mb-5">
        MCP servers give your agent new capabilities — search products, send
        emails, query databases. Connect a server and its tools become available
        in the next cognitive cycle.
      </p>
      <button
        onClick={onConnect}
        className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
      >
        Connect Server
      </button>
    </div>
  );
}
