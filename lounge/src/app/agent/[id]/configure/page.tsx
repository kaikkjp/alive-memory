"use client";

import { useState, useEffect, use, useCallback } from "react";
import AgentNav from "@/components/AgentNav";

interface IdentityConfig {
  identity_compact: string;
  voice_rules: string[];
  communication_style: string;
  language: string;
  greeting: string;
  boundaries: string;
}

interface Capability {
  name: string;
  description: string;
  energy_cost: number;
  enabled: boolean;
}

interface DepthSlider {
  group: string;
  label: string;
  param_path: string;
  min: number;
  max: number;
  default: number;
  value: number;
}

const DEFAULT_CONFIG: IdentityConfig = {
  identity_compact: "",
  voice_rules: [],
  communication_style: "",
  language: "English",
  greeting: "",
  boundaries: "",
};

const DEPTH_SLIDERS: Omit<DepthSlider, "value">[] = [
  { group: "Inner Drives", label: "Curiosity", param_path: "hypothalamus.equilibria.diversive_curiosity", min: 0.2, max: 0.8, default: 0.40 },
  { group: "Inner Drives", label: "Social hunger", param_path: "hypothalamus.equilibria.social_hunger", min: 0.3, max: 0.9, default: 0.45 },
  { group: "Inner Drives", label: "Expression need", param_path: "hypothalamus.equilibria.expression_need", min: 0.2, max: 0.8, default: 0.35 },
  { group: "Inner Drives", label: "Mood valence", param_path: "hypothalamus.equilibria.mood_valence", min: -0.85, max: 0.5, default: 0.05 },
  { group: "Morning Reset", label: "Wake energy", param_path: "sleep.morning.energy", min: 0.5, max: 1.0, default: 1.0 },
  { group: "Morning Reset", label: "Wake curiosity", param_path: "sleep.morning.curiosity", min: 0.2, max: 0.8, default: 0.5 },
  { group: "Morning Reset", label: "Wake social", param_path: "sleep.morning.social_hunger", min: 0.2, max: 0.8, default: 0.5 },
  { group: "Voice", label: "Formality", param_path: "communication_style.formality", min: 0.0, max: 1.0, default: 0.5 },
  { group: "Voice", label: "Verbosity", param_path: "communication_style.verbosity", min: 0.0, max: 1.0, default: 0.4 },
];

export default function ConfigurePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tab, setTab] = useState<"personality" | "depths" | "capabilities">("personality");
  const [config, setConfig] = useState<IdentityConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  // Depths state
  const [depths, setDepths] = useState<DepthSlider[]>([]);
  const [depthsDirty, setDepthsDirty] = useState(false);
  const [depthsSaving, setDepthsSaving] = useState(false);
  const [depthsSaved, setDepthsSaved] = useState(false);

  // Capabilities state
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [capsLoading, setCapsLoading] = useState(false);

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const fetchCapabilities = useCallback(async () => {
    setCapsLoading(true);
    try {
      const res = await fetch(`/api/agents/${id}/capabilities`);
      if (res.ok) {
        const data = await res.json();
        setCapabilities(data.capabilities || []);
      }
    } catch {
      // ignore
    } finally {
      setCapsLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (tab === "capabilities") fetchCapabilities();
  }, [tab, fetchCapabilities]);

  useEffect(() => {
    if (tab === "depths") {
      // Initialize depths with defaults
      setDepths(DEPTH_SLIDERS.map((s) => ({ ...s, value: s.default })));
    }
  }, [tab]);

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

  async function handleSaveDepths() {
    setDepthsSaving(true);
    setDepthsSaved(false);

    const changed = depths.filter(
      (s) => Math.abs(s.value - s.default) > 0.001
    );

    try {
      for (const slider of changed) {
        await fetch(`/api/agents/${id}/whispers`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            param_path: slider.param_path,
            new_value: slider.value.toString(),
          }),
        });
      }
      setDepthsSaved(true);
      setDepthsDirty(false);
      setTimeout(() => setDepthsSaved(false), 3000);
    } catch {
      setError("Failed to queue changes");
    } finally {
      setDepthsSaving(false);
    }
  }

  async function handleToggleCapability(name: string, enabled: boolean) {
    // Optimistic update
    setCapabilities((caps) =>
      caps.map((c) => (c.name === name ? { ...c, enabled } : c))
    );

    try {
      const res = await fetch(`/api/agents/${id}/capabilities`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: name, enabled }),
      });
      if (!res.ok) {
        // Revert
        setCapabilities((caps) =>
          caps.map((c) => (c.name === name ? { ...c, enabled: !enabled } : c))
        );
      }
    } catch {
      // Revert
      setCapabilities((caps) =>
        caps.map((c) => (c.name === name ? { ...c, enabled: !enabled } : c))
      );
    }
  }

  function updateConfig(field: keyof IdentityConfig, value: string | string[]) {
    setConfig((prev) => ({ ...prev, [field]: value }));
  }

  function updateDepth(index: number, value: number) {
    setDepths((prev) =>
      prev.map((s, i) => (i === index ? { ...s, value } : s))
    );
    setDepthsDirty(true);
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

  // Group depths by group name
  const depthGroups: Record<string, DepthSlider[]> = {};
  for (const d of depths) {
    (depthGroups[d.group] ??= []).push(d);
  }

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="configure" />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          {/* Tab switcher */}
          <div className="flex gap-1 mb-6 bg-[#12121a] rounded-lg p-1 w-fit">
            {(["personality", "depths", "capabilities"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 rounded-md text-sm capitalize transition-colors ${
                  tab === t
                    ? "bg-[#262626] text-white"
                    : "text-[#737373] hover:text-white"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Personality tab */}
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
                  className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors resize-y font-mono"
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

              {/* Save bar */}
              <div className="mt-8 pt-4 border-t border-[#262620] flex items-center gap-3">
                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={saving}
                  className="px-5 py-2.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
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
          )}

          {/* Depths tab */}
          {tab === "depths" && (
            <div className="space-y-6">
              <div className="bg-[#12121a] border border-[#262620] rounded-lg p-4">
                <p className="text-sm text-[#a3a3a3]">
                  These changes take effect during her next sleep cycle. You can
                  trigger rest from the Lounge.
                </p>
              </div>

              {Object.entries(depthGroups).map(([group, sliders]) => (
                <div key={group}>
                  <h3 className="text-sm font-medium text-[#d4a574] mb-3">
                    {group}
                  </h3>
                  <div className="space-y-4">
                    {sliders.map((slider) => {
                      const globalIndex = depths.indexOf(slider);
                      return (
                        <DepthSliderControl
                          key={slider.param_path}
                          slider={slider}
                          onChange={(v) => updateDepth(globalIndex, v)}
                        />
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* Save bar */}
              <div className="pt-4 border-t border-[#262620] flex items-center gap-3">
                <button
                  onClick={handleSaveDepths}
                  disabled={depthsSaving || !depthsDirty}
                  className="px-5 py-2.5 bg-[#6b5b8a] hover:bg-[#7b6b9a] text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                >
                  {depthsSaving ? "Queuing..." : "Queue changes"}
                </button>
                {depthsSaved && (
                  <span className="text-sm text-[#22c55e]">
                    Queued. Changes integrate during next rest.
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Capabilities tab */}
          {tab === "capabilities" && (
            <div className="space-y-4">
              <div className="bg-[#12121a] border border-[#262620] rounded-lg p-4">
                <p className="text-sm text-[#a3a3a3]">
                  Toggle which actions the agent can take. Changes take effect
                  immediately.
                </p>
              </div>

              {capsLoading ? (
                <p className="text-sm text-[#737373]">Loading capabilities...</p>
              ) : capabilities.length === 0 ? (
                <p className="text-sm text-[#525252]">
                  No capabilities registered.
                </p>
              ) : (
                <div className="space-y-2">
                  {capabilities.map((cap) => (
                    <div
                      key={cap.name}
                      className="flex items-center justify-between p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-mono text-[#d4d4d4]">
                            {cap.name}
                          </span>
                          {cap.energy_cost > 0 && (
                            <span className="text-xs text-[#525252]">
                              {cap.energy_cost.toFixed(2)} energy
                            </span>
                          )}
                        </div>
                        {cap.description && (
                          <p className="text-xs text-[#737373] mt-0.5 truncate">
                            {cap.description}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() =>
                          handleToggleCapability(cap.name, !cap.enabled)
                        }
                        className={`ml-3 w-10 h-5 rounded-full transition-colors relative shrink-0 ${
                          cap.enabled ? "bg-[#d4a574]" : "bg-[#262626]"
                        }`}
                      >
                        <div
                          className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                            cap.enabled ? "left-5" : "left-0.5"
                          }`}
                        />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-md mx-4">
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
                className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-lg text-sm font-medium transition-colors"
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

function DepthSliderControl({
  slider,
  onChange,
}: {
  slider: DepthSlider;
  onChange: (v: number) => void;
}) {
  const range = slider.max - slider.min;
  const defaultPct = ((slider.default - slider.min) / range) * 100;
  const changed = Math.abs(slider.value - slider.default) > 0.001;

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-sm text-[#a3a3a3]">{slider.label}</span>
        <span className={`text-xs font-mono ${changed ? "text-[#d4a574]" : "text-[#525252]"}`}>
          {slider.value.toFixed(2)}
        </span>
      </div>
      <div className="relative">
        <input
          type="range"
          min={slider.min}
          max={slider.max}
          step={0.01}
          value={slider.value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full h-2 bg-[#262626] rounded-full appearance-none cursor-pointer accent-[#d4a574] [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[#d4a574]"
        />
        {/* Default marker */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-0.5 h-4 bg-[#525252] pointer-events-none"
          style={{ left: `${defaultPct}%` }}
        />
      </div>
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
    "w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors resize-y";

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
