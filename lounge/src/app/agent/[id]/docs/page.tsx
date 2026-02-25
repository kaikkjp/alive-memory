"use client";

import { useState, use } from "react";
import AgentNav from "@/components/AgentNav";

const CODE_EXAMPLES = {
  curl: (agentId: string) => `curl -X POST https://api.alive.kaikk.jp/${agentId}/chat \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Hello", "visitor_id": "my-app-user-1"}'`,
  python: (agentId: string) => `import requests

response = requests.post(
    f"https://api.alive.kaikk.jp/${agentId}/chat",
    headers={
        "Authorization": "Bearer YOUR_API_KEY",
        "Content-Type": "application/json",
    },
    json={
        "message": "Hello",
        "visitor_id": "my-app-user-1",
    },
)

data = response.json()
print(data["response"])`,
  javascript: (agentId: string) => `const response = await fetch(
  "https://api.alive.kaikk.jp/${agentId}/chat",
  {
    method: "POST",
    headers: {
      "Authorization": "Bearer YOUR_API_KEY",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: "Hello",
      visitor_id: "my-app-user-1",
    }),
  }
);

const data = await response.json();
console.log(data.response);`,
};

export default function DocsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [codeLang, setCodeLang] = useState<"curl" | "python" | "javascript">("curl");
  const [copied, setCopied] = useState<string | null>(null);

  function copyToClipboard(text: string, label: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 2000);
    });
  }

  const endpoint = `https://api.alive.kaikk.jp/${id}`;

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="docs" />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-8">
          <h1 className="text-xl font-semibold mb-1">API Documentation</h1>
          <p className="text-sm text-[#9a8c7a] mb-8">
            Integrate this agent into your application.
          </p>

          {/* Authentication */}
          <Section title="Authentication">
            <p className="text-sm text-[#a3a3a3] mb-3">
              All requests require a Bearer token in the Authorization header. Generate API keys from the API Keys page.
            </p>
            <CodeBlock
              code={`Authorization: Bearer YOUR_API_KEY`}
              label="auth-header"
              onCopy={copyToClipboard}
              copied={copied}
            />
          </Section>

          {/* Chat endpoint */}
          <Section title="Chat">
            <EndpointBadge method="POST" url={`${endpoint}/chat`} onCopy={() => copyToClipboard(`${endpoint}/chat`, "chat-url")} copied={copied === "chat-url"} />

            <h4 className="text-sm font-medium mt-5 mb-2">Request Body</h4>
            <CodeBlock
              code={`{
  "message": "string",       // required — the message text
  "visitor_id": "string"     // required — unique ID for the conversation participant
}`}
              label="chat-request"
              onCopy={copyToClipboard}
              copied={copied}
            />

            <h4 className="text-sm font-medium mt-5 mb-2">Response</h4>
            <CodeBlock
              code={`{
  "response": "string",      // the agent's reply (null if no dialogue)
  "message": "string",       // status message if no response
  "timestamp": "string",     // ISO 8601 timestamp
  "cycle_id": "number"       // internal cycle identifier
}`}
              label="chat-response"
              onCopy={copyToClipboard}
              copied={copied}
            />

            <h4 className="text-sm font-medium mt-5 mb-2">Example Response</h4>
            <CodeBlock
              code={`{
  "response": "Hello... I was just thinking about something.",
  "timestamp": "2026-02-25T14:30:00.000Z",
  "cycle_id": 4231
}`}
              label="chat-example"
              onCopy={copyToClipboard}
              copied={copied}
            />
          </Section>

          {/* State endpoint */}
          <Section title="State">
            <EndpointBadge method="GET" url={`${endpoint}/state`} onCopy={() => copyToClipboard(`${endpoint}/state`, "state-url")} copied={copied === "state-url"} />

            <h4 className="text-sm font-medium mt-5 mb-2">Response</h4>
            <CodeBlock
              code={`{
  "status": "active" | "inactive",
  "mood": {
    "valence": "number",     // -1 to 1 (negative to positive)
    "arousal": "number"      // 0 to 1 (calm to energized)
  },
  "energy": "number",        // 0 to 1
  "engaged": "boolean",      // true if in conversation
  "drives": {
    "curiosity": { "value": "number", "label": "string" },
    "social_hunger": { "value": "number", "label": "string" },
    "expression_need": { "value": "number", "label": "string" }
  },
  "mood_word": "string",     // e.g. "contemplative", "energized"
  "state_description": "string",
  "timestamp": "string"
}`}
              label="state-response"
              onCopy={copyToClipboard}
              copied={copied}
            />
          </Section>

          {/* Code examples */}
          <Section title="Code Examples">
            <div className="flex gap-1 mb-3 bg-[#12121a] rounded-lg p-1 w-fit">
              {(["curl", "python", "javascript"] as const).map((lang) => (
                <button
                  key={lang}
                  onClick={() => setCodeLang(lang)}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    codeLang === lang
                      ? "bg-[#262620] text-[#d4a574]"
                      : "text-[#737373] hover:text-[#a3a3a3]"
                  }`}
                >
                  {lang}
                </button>
              ))}
            </div>
            <CodeBlock
              code={CODE_EXAMPLES[codeLang](id)}
              label={`example-${codeLang}`}
              onCopy={copyToClipboard}
              copied={copied}
            />
          </Section>

          {/* Rate limits */}
          <Section title="Rate Limits">
            <p className="text-sm text-[#a3a3a3]">
              Each API key has a configurable rate limit (default: 60 requests/minute). Exceeding the limit returns <code className="text-xs bg-[#12121a] px-1.5 py-0.5 rounded text-[#d4a574]">429 Too Many Requests</code>. The agent processes one conversation at a time — if already engaged, requests queue and may time out after 30 seconds.
            </p>
          </Section>

          {/* Errors */}
          <Section title="Errors" last>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[#737373] uppercase">
                    <th className="pb-2 pr-4 font-medium">Status</th>
                    <th className="pb-2 pr-4 font-medium">Meaning</th>
                  </tr>
                </thead>
                <tbody className="text-[#a3a3a3]">
                  <ErrorRow code="401" meaning="Missing or invalid API key" />
                  <ErrorRow code="404" meaning="Agent not found" />
                  <ErrorRow code="429" meaning="Rate limit exceeded" />
                  <ErrorRow code="503" meaning="Agent is not running" />
                  <ErrorRow code="504" meaning="Agent did not respond within timeout" />
                </tbody>
              </table>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children, last }: { title: string; children: React.ReactNode; last?: boolean }) {
  return (
    <div className={last ? "mb-12" : "mb-10 pb-10 border-b border-[#1e1e1a]"}>
      <h2 className="text-base font-semibold mb-4">{title}</h2>
      {children}
    </div>
  );
}

function EndpointBadge({ method, url, onCopy, copied }: { method: string; url: string; onCopy: () => void; copied: boolean }) {
  const methodColor = method === "POST" ? "text-[#d4a574]" : "text-[#22c55e]";
  return (
    <div className="flex items-center gap-3 bg-[#12121a] border border-[#262620] rounded-lg px-4 py-2.5">
      <span className={`text-xs font-bold ${methodColor}`}>{method}</span>
      <code className="text-sm text-[#a3a3a3] flex-1 break-all font-mono">{url}</code>
      <button
        onClick={onCopy}
        className="text-xs text-[#737373] hover:text-[#d4a574] transition-colors shrink-0"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function CodeBlock({ code, label, onCopy, copied }: { code: string; label: string; onCopy: (text: string, label: string) => void; copied: string | null }) {
  return (
    <div className="relative group">
      <pre className="bg-[#0a0a0f] border border-[#1e1e1a] rounded-lg p-4 overflow-x-auto text-xs font-mono text-[#a3a3a3] leading-relaxed">
        {code}
      </pre>
      <button
        onClick={() => onCopy(code, label)}
        className="absolute top-2 right-2 text-xs px-2 py-1 rounded bg-[#1e1e1a] text-[#737373] hover:text-[#d4a574] opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied === label ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function ErrorRow({ code, meaning }: { code: string; meaning: string }) {
  return (
    <tr>
      <td className="py-1.5 pr-4">
        <code className="text-xs bg-[#12121a] px-1.5 py-0.5 rounded text-[#d4a574]">{code}</code>
      </td>
      <td className="py-1.5">{meaning}</td>
    </tr>
  );
}
