"use client";

import { useState, useEffect, useCallback } from "react";

interface IdentityConfig {
  identity_compact: string;
  voice_rules: string[];
  communication_style: string;
  language: string;
  greeting: string;
  boundaries: string;
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

interface SettingsDrawerProps {
  agentId: string;
  open: boolean;
  onClose: () => void;
  onToast: (msg: string) => void;
}

export default function SettingsDrawer({ agentId, open, onClose, onToast }: SettingsDrawerProps) {
  const [tab, setTab] = useState<"identity" | "depths">("identity");
  const [config, setConfig] = useState<IdentityConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");

  // Depths state
  const [depths, setDepths] = useState<DepthSlider[]>([]);
  const [depthsDirty, setDepthsDirty] = useState(false);
  const [depthsSaving, setDepthsSaving] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${agentId}/config`);
      if (res.ok) {
        const data = await res.json();
        if (data.config && Object.keys(data.config).length > 0) {
          // Normalize types — YAML parser may return string[] for boundaries
          // and string for voice_rules depending on YAML format
          const raw = data.config;
          const normalized: Partial<IdentityConfig> = { ...raw };
          if (Array.isArray(raw.voice_rules)) {
            normalized.voice_rules = raw.voice_rules;
          } else if (typeof raw.voice_rules === "string") {
            normalized.voice_rules = raw.voice_rules.split("\n").filter(Boolean);
          }
          if (Array.isArray(raw.boundaries)) {
            normalized.boundaries = raw.boundaries.join("\n");
          } else if (typeof raw.boundaries !== "string") {
            normalized.boundaries = "";
          }
          setConfig({ ...DEFAULT_CONFIG, ...normalized });
        }
      }
    } catch {
      // use defaults
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (open) {
      fetchConfig();
      setDepths(DEPTH_SLIDERS.map((s) => ({ ...s, value: s.default })));
      // Reset transient state on reopen
      setDepthsDirty(false);
      setError("");
      setShowConfirm(false);
    }
  }, [open, fetchConfig]);

  // Escape key: dismiss confirm modal first, then close drawer
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (showConfirm) {
          setShowConfirm(false);
        } else {
          onClose();
        }
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose, showConfirm]);

  async function handleSave() {
    setShowConfirm(false);
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`/api/agents/${agentId}/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity: config }),
      });
      if (res.ok) {
        onToast("Saved. Agent restarting...");
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
    setError("");
    const changed = depths.filter((s) => Math.abs(s.value - s.default) > 0.001);
    try {
      for (const slider of changed) {
        const res = await fetch(`/api/agents/${agentId}/whispers`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            param_path: slider.param_path,
            new_value: slider.value.toString(),
          }),
        });
        if (!res.ok) {
          setError(`Failed to queue ${slider.label}`);
          return;
        }
      }
      setDepthsDirty(false);
      onToast("Queued. Changes integrate during next rest.");
    } catch {
      setError("Failed to queue changes");
    } finally {
      setDepthsSaving(false);
    }
  }

  function updateConfig(field: keyof IdentityConfig, value: string | string[]) {
    setConfig((prev) => ({ ...prev, [field]: value }));
  }

  function updateDepth(index: number, value: number) {
    setDepths((prev) => prev.map((s, i) => (i === index ? { ...s, value } : s)));
    setDepthsDirty(true);
  }

  if (!open) return null;

  // Group depths
  const depthGroups: Record<string, DepthSlider[]> = {};
  for (const d of depths) {
    (depthGroups[d.group] ??= []).push(d);
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed top-0 right-0 bottom-0 w-[400px] max-w-[90vw] bg-[#0e0e14] border-l border-[#1e1e1a] z-50 flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e1e1a]">
          <h2 className="text-sm font-medium text-[#e5e5e5]">Settings</h2>
          <button
            onClick={onClose}
            className="text-[#525252] hover:text-white transition-colors text-lg leading-none p-1"
          >
            &times;
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 px-4 pt-3 pb-2">
          {(["identity", "depths"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-md text-xs capitalize transition-colors ${
                tab === t
                  ? "bg-[#262626] text-white"
                  : "text-[#737373] hover:text-white"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {loading ? (
            <div className="space-y-4 pt-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="space-y-2">
                  <div className="h-3 w-20 bg-[#1e1e1a] rounded animate-skeleton" />
                  <div className="h-8 bg-[#1e1e1a] rounded-lg animate-skeleton" />
                </div>
              ))}
            </div>
          ) : tab === "identity" ? (
            <div className="space-y-4 pt-2 animate-tab-fade" key="identity">
              <DrawerField
                label="Identity"
                description="Core character description"
                value={config.identity_compact}
                onChange={(v) => updateConfig("identity_compact", v)}
                multiline
                rows={6}
              />
              <DrawerField
                label="Greeting"
                description="How the agent greets visitors"
                value={config.greeting}
                onChange={(v) => updateConfig("greeting", v)}
                multiline
                rows={2}
              />
              <DrawerField
                label="Communication Style"
                value={config.communication_style}
                onChange={(v) => updateConfig("communication_style", v)}
                placeholder="e.g., warm, formal, terse"
              />
              <DrawerField
                label="Language"
                value={config.language}
                onChange={(v) => updateConfig("language", v)}
                placeholder="e.g., English, Japanese"
              />
              <div>
                <label className="block text-xs font-medium text-[#a3a3a3] mb-1">Voice Rules</label>
                <p className="text-[10px] text-[#525252] mb-1.5">One per line</p>
                <textarea
                  value={config.voice_rules.join("\n")}
                  onChange={(e) =>
                    updateConfig("voice_rules", e.target.value.split("\n").filter((l) => l.trim()))
                  }
                  rows={4}
                  className="w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-md text-xs focus:outline-none focus:border-[#d4a574] transition-colors resize-y font-mono"
                  placeholder={"never say 'as an AI'\nprefer short sentences"}
                />
              </div>
              <DrawerTagInput
                label="Boundaries"
                description="Press Enter to add"
                tags={config.boundaries ? config.boundaries.split("\n").filter(Boolean) : []}
                onChange={(tags) => updateConfig("boundaries", tags.join("\n"))}
                placeholder="e.g., no personal advice"
              />

              {/* Save */}
              <div className="pt-3 border-t border-[#1e1e1a]">
                <p className="text-[10px] text-[#525252] mb-2">
                  Changes apply on next thought cycle. Agent will restart.
                </p>
                <button
                  onClick={() => setShowConfirm(true)}
                  disabled={saving}
                  className="w-full py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-md text-xs font-medium transition-colors"
                >
                  {saving ? "Saving..." : "Save & Restart"}
                </button>
                {error && <p className="text-xs text-[#ef4444] mt-2">{error}</p>}
              </div>
            </div>
          ) : (
            <div className="space-y-4 pt-2 animate-tab-fade" key="depths">
              <div className="bg-[#12121a] border border-[#262620] rounded-lg p-3">
                <p className="text-[10px] text-[#a3a3a3]">
                  Changes integrate during next sleep cycle. Trigger rest from the Lounge.
                </p>
              </div>

              {Object.entries(depthGroups).map(([group, sliders]) => (
                <div key={group}>
                  <h3 className="text-xs font-medium text-[#d4a574] mb-2">{group}</h3>
                  <div className="space-y-3">
                    {sliders.map((slider) => {
                      const globalIndex = depths.indexOf(slider);
                      return (
                        <DrawerDepthSlider
                          key={slider.param_path}
                          slider={slider}
                          onChange={(v) => updateDepth(globalIndex, v)}
                        />
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* Save */}
              <div className="pt-3 border-t border-[#1e1e1a]">
                <button
                  onClick={handleSaveDepths}
                  disabled={depthsSaving || !depthsDirty}
                  className="w-full py-2 bg-[#6b5b8a] hover:bg-[#7b6b9a] text-white disabled:opacity-50 rounded-md text-xs font-medium transition-colors"
                >
                  {depthsSaving ? "Queuing..." : "Queue changes"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Restart confirmation */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[60]">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-sm mx-4">
            <h3 className="text-base font-semibold mb-2">Restart Agent?</h3>
            <p className="text-sm text-[#a3a3a3] mb-4">
              Saving will restart your agent. Active conversations will be interrupted.
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
    </>
  );
}

function DrawerField({
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
    "w-full px-3 py-2 bg-[#12121a] border border-[#262620] rounded-md text-xs focus:outline-none focus:border-[#d4a574] transition-colors resize-y";

  return (
    <div>
      <label className="block text-xs font-medium text-[#a3a3a3] mb-1">{label}</label>
      {description && <p className="text-[10px] text-[#525252] mb-1.5">{description}</p>}
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

function DrawerTagInput({
  label,
  description,
  tags,
  onChange,
  placeholder,
}: {
  label: string;
  description?: string;
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}) {
  const [input, setInput] = useState("");

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      if (!tags.includes(input.trim())) {
        onChange([...tags, input.trim()]);
      }
      setInput("");
    }
    if (e.key === "Backspace" && !input && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  }

  return (
    <div>
      <label className="block text-xs font-medium text-[#a3a3a3] mb-1">{label}</label>
      {description && <p className="text-[10px] text-[#525252] mb-1.5">{description}</p>}
      <div className="flex flex-wrap gap-1.5 p-2 bg-[#12121a] border border-[#262620] rounded-md min-h-[36px] focus-within:border-[#d4a574] transition-colors">
        {tags.map((tag, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-[#262626] text-xs rounded-md"
          >
            {tag}
            <button
              onClick={() => onChange(tags.filter((_, idx) => idx !== i))}
              className="text-[#737373] hover:text-[#ef4444] text-[10px] ml-0.5 transition-colors"
              type="button"
            >
              &times;
            </button>
          </span>
        ))}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[80px] bg-transparent text-xs focus:outline-none py-0.5"
        />
      </div>
    </div>
  );
}

function DrawerDepthSlider({
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
        <span className="text-xs text-[#a3a3a3]">{slider.label}</span>
        <span className={`text-[10px] font-mono ${changed ? "text-[#d4a574]" : "text-[#525252]"}`}>
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
          className="w-full h-1.5 bg-[#262626] rounded-full appearance-none cursor-pointer accent-[#d4a574] [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[#d4a574]"
        />
        <div
          className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 bg-[#525252] pointer-events-none"
          style={{ left: `${defaultPct}%` }}
        />
      </div>
    </div>
  );
}
