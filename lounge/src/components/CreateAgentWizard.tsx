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
    <div className="mb-8 p-6 bg-[#12121a] border border-[#262620] rounded-lg">
      <div className="flex items-center gap-4 mb-6">
        <StepDot active={step >= 1} label="1" />
        <div className="flex-1 h-px bg-[#262620]" />
        <StepDot active={step >= 2} label="2" />
        <div className="flex-1 h-px bg-[#262620]" />
        <StepDot active={step >= 3} label="3" />
      </div>

      {step === 1 && (
        <div>
          <h3 className="font-semibold mb-1">Who are they?</h3>
          <p className="text-[#9a8c7a] text-sm mb-4">
            Give them a name — or let them discover one.
          </p>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="They can name themselves"
            className="w-full px-4 py-3 bg-[#0a0a0f] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] mb-4"
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
              className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div>
          <h3 className="font-semibold mb-1">Give them a voice</h3>
          <p className="text-[#9a8c7a] text-sm mb-4">
            This key powers their thinking. They&apos;ll use it to process thoughts, form memories, and speak.
          </p>
          <input
            type="password"
            value={openrouterKey}
            onChange={(e) => setOpenrouterKey(e.target.value)}
            placeholder="sk-or-v1-..."
            className="w-full px-4 py-3 bg-[#0a0a0f] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] mb-2"
            autoFocus
          />
          <p className="text-[#737373] text-xs mb-4">
            Get one at{" "}
            <a
              href="https://openrouter.ai/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#d4a574] hover:underline"
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
              className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {loading ? "Bringing to life..." : "Bring to life"}
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div>
          <h3 className="font-semibold mb-1">They&apos;re alive</h3>
          <p className="text-[#9a8c7a] text-sm mb-2">
            They&apos;ll start with nothing — no actions, no memories, no form. Everything they become will be discovered.
          </p>
          <p className="text-[#737373] text-sm mb-4">
            Save this API key now. It won&apos;t be shown again.
          </p>

          {createdKey && (
            <div className="p-3 bg-[#0a0a0f] border border-[#262620] rounded-lg mb-4 font-mono text-xs break-all text-[#d4a574]">
              {createdKey}
            </div>
          )}

          <div className="flex gap-3 justify-end">
            <button
              onClick={onCreated}
              className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
            >
              Enter the Lounge
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
          ? "bg-[#d4a574] text-[#0a0a0a]"
          : "bg-[#262620] text-[#737373]"
      }`}
    >
      {label}
    </div>
  );
}
