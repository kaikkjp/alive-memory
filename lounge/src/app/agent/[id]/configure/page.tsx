"use client";

import { useState, useEffect, use } from "react";
import AgentNav from "@/components/AgentNav";

interface IdentityConfig {
  identity_compact: string;
  voice_rules: string[];
  communication_style: string;
  language: string;
  greeting: string;
  boundaries: string;
}

const DEFAULT_CONFIG: IdentityConfig = {
  identity_compact: "",
  voice_rules: [],
  communication_style: "",
  language: "English",
  greeting: "",
  boundaries: "",
};

export default function ConfigurePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tab, setTab] = useState<"personality" | "behavior">("personality");
  const [config, setConfig] = useState<IdentityConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function fetchConfig() {
    try {
      const res = await fetch(`/api/agents/${id}/config`);
      if (res.ok) {
        const data = await res.json();
        if (data.config && Object.keys(data.config).length > 0) {
          setConfig({ ...DEFAULT_CONFIG, ...data.config });
        }
      }
    } catch {
      // use defaults
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    setShowConfirm(false);
    setSaving(true);
    setError("");
    setSaved(false);

    try {
      const res = await fetch(`/api/agents/${id}/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity: config }),
      });

      if (res.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        const data = await res.json();
        setError(data.error || "Failed to save");
      }
    } catch {
      setError("Connection error");
    } finally {
      setSaving(false);
    }
  }

  function updateConfig(field: keyof IdentityConfig, value: string | string[]) {
    setConfig((prev) => ({ ...prev, [field]: value }));
  }

  if (loading) {
    return (
      <div className="flex flex-col h-screen">
        <AgentNav agentId={id} active="configure" />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[#737373] text-sm">Loading configuration...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="configure" />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          {/* Tab switcher */}
          <div className="flex gap-1 mb-6 bg-[#141414] rounded-lg p-1 w-fit">
            <button
              onClick={() => setTab("personality")}
              className={`px-4 py-2 rounded-md text-sm transition-colors ${
                tab === "personality"
                  ? "bg-[#262626] text-white"
                  : "text-[#737373] hover:text-white"
              }`}
            >
              Personality
            </button>
            <button
              onClick={() => setTab("behavior")}
              className={`px-4 py-2 rounded-md text-sm transition-colors ${
                tab === "behavior"
                  ? "bg-[#262626] text-white"
                  : "text-[#737373] hover:text-white"
              }`}
            >
              Behavior
            </button>
          </div>

          {tab === "personality" && (
            <div className="space-y-5">
              <ConfigField
                label="Identity"
                description="Core character description. Who is this agent?"
                value={config.identity_compact}
                onChange={(v) => updateConfig("identity_compact", v)}
                multiline
                rows={8}
              />
              <ConfigField
                label="Greeting"
                description="How the agent greets new visitors."
                value={config.greeting}
                onChange={(v) => updateConfig("greeting", v)}
                multiline
                rows={2}
              />
              <ConfigField
                label="Communication Style"
                description="Tone and manner of speaking."
                value={config.communication_style}
                onChange={(v) => updateConfig("communication_style", v)}
                placeholder="e.g., warm and conversational, formal, terse"
              />
              <ConfigField
                label="Language"
                description="Primary language for responses."
                value={config.language}
                onChange={(v) => updateConfig("language", v)}
                placeholder="e.g., English, Japanese, bilingual"
              />
              <div>
                <label className="block text-sm font-medium mb-1">
                  Voice Rules
                </label>
                <p className="text-xs text-[#737373] mb-2">
                  Patterns the agent should follow or avoid. One per line.
                </p>
                <textarea
                  value={config.voice_rules.join("\n")}
                  onChange={(e) =>
                    updateConfig(
                      "voice_rules",
                      e.target.value.split("\n").filter((l) => l.trim())
                    )
                  }
                  rows={5}
                  className="w-full px-3 py-2 bg-[#141414] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6] transition-colors resize-y font-mono"
                  placeholder={"never say 'as an AI'\ndon't use exclamation marks\nprefer short sentences"}
                />
              </div>
              <ConfigField
                label="Boundaries"
                description="Topics or behaviors the agent should refuse."
                value={config.boundaries}
                onChange={(v) => updateConfig("boundaries", v)}
                multiline
                rows={3}
              />
            </div>
          )}

          {tab === "behavior" && (
            <div className="space-y-6">
              <p className="text-sm text-[#737373]">
                Behavior tuning controls will be available in a future update.
                Current defaults provide a balanced personality profile.
              </p>
              <div className="space-y-4">
                <BehaviorPreview label="Curiosity" value={0.6} />
                <BehaviorPreview label="Sociability" value={0.5} />
                <BehaviorPreview label="Assertiveness" value={0.4} />
                <BehaviorPreview label="Patience" value={0.7} />
                <BehaviorPreview label="Playfulness" value={0.5} />
              </div>
              <p className="text-xs text-[#737373]">
                These values are read-only previews. Edit your agent&apos;s
                alive_config.yaml directly for advanced tuning.
              </p>
            </div>
          )}

          {/* Save bar */}
          <div className="mt-8 pt-4 border-t border-[#262626] flex items-center gap-3">
            <button
              onClick={() => setShowConfirm(true)}
              disabled={saving || tab === "behavior"}
              className="px-5 py-2.5 bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {saving ? "Saving..." : "Save & Restart"}
            </button>
            {saved && (
              <span className="text-sm text-[#22c55e]">
                Saved. Agent restarting...
              </span>
            )}
            {error && <span className="text-sm text-[#ef4444]">{error}</span>}
          </div>
        </div>
      </div>

      {/* Confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262626] rounded-xl p-6 max-w-md mx-4">
            <h3 className="text-lg font-semibold mb-2">Restart Agent?</h3>
            <p className="text-sm text-[#a3a3a3] mb-5">
              Saving will restart your agent. Active conversations will be
              interrupted.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="px-4 py-2 bg-[#3b82f6] hover:bg-[#2563eb] rounded-lg text-sm font-medium transition-colors"
              >
                Save & Restart
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigField({
  label,
  description,
  value,
  onChange,
  multiline,
  rows,
  placeholder,
}: {
  label: string;
  description?: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
}) {
  const cls =
    "w-full px-3 py-2 bg-[#141414] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6] transition-colors resize-y";

  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {description && (
        <p className="text-xs text-[#737373] mb-2">{description}</p>
      )}
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows || 4}
          className={cls}
          placeholder={placeholder}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cls}
          placeholder={placeholder}
        />
      )}
    </div>
  );
}

function BehaviorPreview({ label, value }: { label: string; value: number }) {
  const pct = value * 100;
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-[#a3a3a3]">{label}</span>
        <span className="text-[#737373]">{value.toFixed(1)}</span>
      </div>
      <div className="h-2 bg-[#262626] rounded-full overflow-hidden">
        <div
          className="h-full bg-[#3b82f6]/50 rounded-full"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
