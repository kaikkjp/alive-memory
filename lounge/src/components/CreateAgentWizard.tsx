"use client";

import { useState } from "react";

interface Props {
  onCreated: () => void;
  onCancel: () => void;
}

export default function CreateAgentWizard({ onCreated, onCancel }: Props) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [openrouterKey, setOpenrouterKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [createdKey, setCreatedKey] = useState("");

  async function handleCreate() {
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          openrouter_key: openrouterKey.trim(),
        }),
      });
      const data = await res.json();

      if (res.ok) {
        setCreatedKey(data.api_key?.key || "");
        setStep(3);
      } else {
        setError(data.error || "Failed to create agent");
      }
    } catch {
      setError("Connection error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mb-8 p-6 bg-[#141414] border border-[#262626] rounded-lg">
      <div className="flex items-center gap-4 mb-6">
        <StepDot active={step >= 1} label="1" />
        <div className="flex-1 h-px bg-[#262626]" />
        <StepDot active={step >= 2} label="2" />
        <div className="flex-1 h-px bg-[#262626]" />
        <StepDot active={step >= 3} label="3" />
      </div>

      {step === 1 && (
        <div>
          <h3 className="font-semibold mb-1">Name your agent</h3>
          <p className="text-[#737373] text-sm mb-4">
            Choose a name and optional role for your character.
          </p>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Luna the Librarian"
            className="w-full px-4 py-3 bg-[#0a0a0a] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6] mb-4"
            autoFocus
          />
          <div className="flex gap-3 justify-end">
            <button
              onClick={onCancel}
              className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => setStep(2)}
              disabled={!name.trim()}
              className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div>
          <h3 className="font-semibold mb-1">OpenRouter API Key</h3>
          <p className="text-[#737373] text-sm mb-4">
            Your agent needs an LLM to think. Paste your OpenRouter API key.
          </p>
          <input
            type="password"
            value={openrouterKey}
            onChange={(e) => setOpenrouterKey(e.target.value)}
            placeholder="sk-or-v1-..."
            className="w-full px-4 py-3 bg-[#0a0a0a] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6] mb-2"
            autoFocus
          />
          <p className="text-[#737373] text-xs mb-4">
            Get one at{" "}
            <a
              href="https://openrouter.ai/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#3b82f6] hover:underline"
            >
              openrouter.ai/keys
            </a>
          </p>

          {error && <p className="text-[#ef4444] text-sm mb-4">{error}</p>}

          <div className="flex gap-3 justify-end">
            <button
              onClick={() => setStep(1)}
              className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
            >
              Back
            </button>
            <button
              onClick={handleCreate}
              disabled={loading || !openrouterKey.trim()}
              className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {loading ? "Creating..." : "Create Agent"}
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div>
          <h3 className="font-semibold mb-1">Agent created</h3>
          <p className="text-[#737373] text-sm mb-4">
            Your agent is starting up. Here is your API key — save it now, it
            will not be shown again.
          </p>

          {createdKey && (
            <div className="p-3 bg-[#0a0a0a] border border-[#262626] rounded-lg mb-4 font-mono text-xs break-all">
              {createdKey}
            </div>
          )}

          <div className="flex gap-3 justify-end">
            <button
              onClick={onCreated}
              className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
            >
              Go to Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function StepDot({ active, label }: { active: boolean; label: string }) {
  return (
    <div
      className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium ${
        active
          ? "bg-[#3b82f6] text-white"
          : "bg-[#262626] text-[#737373]"
      }`}
    >
      {label}
    </div>
  );
}
