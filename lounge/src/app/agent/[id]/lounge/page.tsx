"use client";

import { useState, useRef, useEffect, use, useCallback } from "react";
import AgentNav from "@/components/AgentNav";
import ConsciousnessCanvas from "@/components/ConsciousnessCanvas";
import MemoryPanel from "@/components/MemoryPanel";

interface Message {
  role: "user" | "agent" | "system";
  text: string;
  timestamp: string;
}

interface RecentAction {
  action: string;
  timestamp: string;
  content?: string;
}

interface AgentState {
  status: string;
  mood?: { valence: number; arousal: number };
  energy?: number;
  engaged?: boolean;
  port?: number;
  recent_actions?: RecentAction[];
  drives?: {
    curiosity: number;
    social_hunger: number;
    expression_need: number;
    rest_need: number;
    energy: number;
    mood_valence: number;
    mood_arousal: number;
    updated_at?: string;
  };
}

function getMoodWord(valence: number, arousal: number): string {
  if (valence > 0.3 && arousal > 0.3) return "excited";
  if (valence > 0.3 && arousal < -0.1) return "serene";
  if (valence > 0.1) return "content";
  if (valence < -0.3 && arousal > 0.3) return "agitated";
  if (valence < -0.3) return "melancholic";
  if (valence < -0.1) return "pensive";
  if (arousal > 0.3) return "alert";
  if (arousal < -0.2) return "drowsy";
  return "neutral";
}

function getMoodColor(valence: number): string {
  if (valence > 0.2) return "#d4a574";
  if (valence < -0.2) return "#8b9dc3";
  return "#9a8c7a";
}

function getStateDescription(state: AgentState): string {
  if (state.status === "offline") return "Offline";
  const energy = state.drives?.energy ?? state.energy ?? 0.5;
  const engaged = state.engaged;
  if (energy < 0.15) return "Exhausted";
  if (engaged) return "In conversation";
  if (energy < 0.3) return "Resting quietly";
  if (energy > 0.8) return "Wide awake";
  return "Present";
}

function formatActionLabel(action: string): string {
  const labels: Record<string, string> = {
    write_journal: "Wrote in her journal",
    browse_web: "Browsed the web",
    post_x_draft: "Drafted a post",
    read_content: "Read something",
    speak: "Spoke",
    sleep: "Rested for a while",
    think: "Thought quietly",
    recall: "Remembered something",
    reflect: "Reflected on things",
  };
  return labels[action] || action.replace(/_/g, " ");
}

export default function LoungePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [agentState, setAgentState] = useState<AgentState | null>(null);
  const [showSidebar, setShowSidebar] = useState(false);
  const [showMemoryPanel, setShowMemoryPanel] = useState(false);
  const [sleeping, setSleeping] = useState(false);
  const [sleepConfirm, setSleepConfirm] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);
  const visitorId = useRef(`lounge-${Date.now()}`);

  const fetchState = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${id}/status`);
      if (res.ok) setAgentState(await res.json());
    } catch {
      // ignore
    }
  }, [id]);

  useEffect(() => {
    fetchState();
    const interval = setInterval(fetchState, 15000);
    return () => clearInterval(interval);
  }, [fetchState]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Desktop: show sidebar by default
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setShowSidebar(mq.matches);
    function handler(e: MediaQueryListEvent) {
      setShowSidebar(e.matches);
    }
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    const userMsg: Message = {
      role: "user",
      text,
      timestamp: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    setSending(true);

    try {
      const res = await fetch(`/api/agents/${id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          visitor_id: visitorId.current,
          source: "manager",
        }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.response) {
          setMessages((m) => [
            ...m,
            {
              role: "agent",
              text: data.response,
              timestamp: data.timestamp || new Date().toISOString(),
            },
          ]);
        } else {
          setMessages((m) => [
            ...m,
            {
              role: "system",
              text: data.message || "No response",
              timestamp: new Date().toISOString(),
            },
          ]);
        }
      } else {
        setMessages((m) => [
          ...m,
          {
            role: "system",
            text: "Failed to reach agent",
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "system",
          text: "Connection error",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setSending(false);
      fetchState();
    }
  }

  async function handleForceSleep() {
    setSleepConfirm(false);
    setSleeping(true);
    try {
      const res = await fetch(`/api/agents/${id}/sleep`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const msg = data.queued
          ? "Will rest after current conversation."
          : "Entering sleep cycle...";
        setMessages((m) => [
          ...m,
          { role: "system", text: msg, timestamp: new Date().toISOString() },
        ]);
        setTimeout(async () => {
          await fetchState();
          if (!data.queued) {
            setMessages((m) => [
              ...m,
              {
                role: "system",
                text: "She stirs. Something feels different.",
                timestamp: new Date().toISOString(),
              },
            ]);
          }
          setSleeping(false);
        }, 5000);
      } else {
        setSleeping(false);
      }
    } catch {
      setSleeping(false);
    }
  }

  // Derive canvas props from agent state
  const moodValence =
    agentState?.drives?.mood_valence ?? agentState?.mood?.valence ?? 0;
  const moodArousal =
    agentState?.drives?.mood_arousal ?? agentState?.mood?.arousal ?? 0;
  const energyVal = agentState?.drives?.energy ?? agentState?.energy ?? 0.5;
  const curiosityVal = agentState?.drives?.curiosity ?? 0.45;
  const socialVal = agentState?.drives?.social_hunger ?? 0.5;
  const expressionVal = agentState?.drives?.expression_need ?? 0.4;
  const restVal = agentState?.drives?.rest_need ?? 0.3;
  const isSleeping = sleeping || energyVal < 0.1;

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="lounge" />

      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel with organism background */}
        <div className="flex-1 flex flex-col relative">
          {/* Living background */}
          <ConsciousnessCanvas
            mood_valence={moodValence}
            energy={energyVal}
            curiosity={curiosityVal}
            social_hunger={socialVal}
            expression_need={expressionVal}
            is_sleeping={isSleeping}
            is_thinking={sending}
          />

          {/* Messages floating over organism */}
          <div className="relative z-10 flex-1 overflow-y-auto px-4 py-6 space-y-6">
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full">
                <p className="text-[#525252] text-sm">
                  Send a message to start the conversation
                </p>
              </div>
            )}
            {messages.map((msg, i) => (
              <ChatBubble key={i} message={msg} />
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="px-4 py-3 rounded-2xl bg-[#1a1510]/70 backdrop-blur-sm">
                  <div className="flex gap-1.5">
                    <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce" />
                    <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce [animation-delay:0.15s]" />
                    <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce [animation-delay:0.3s]" />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEnd} />
          </div>

          {/* Input */}
          <form
            onSubmit={handleSend}
            className="relative z-10 border-t border-[#1e1e1a]/50 px-4 py-3 flex gap-3 bg-[#0a0a0f]/80 backdrop-blur-sm"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a message..."
              className="flex-1 px-4 py-2.5 bg-[#12121a]/80 border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors"
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="px-4 py-2.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              Send
            </button>
            {/* Mobile sidebar toggle */}
            <button
              type="button"
              onClick={() => setShowSidebar(!showSidebar)}
              className="md:hidden px-3 py-2.5 border border-[#262620] text-[#737373] hover:text-white rounded-lg text-sm transition-colors"
              title="Toggle sidebar"
            >
              ☰
            </button>
          </form>
        </div>

        {/* Desktop sidebar toggle */}
        <button
          onClick={() => setShowSidebar(!showSidebar)}
          className="hidden md:flex items-center px-1 border-l border-[#1e1e1a] text-[#737373] hover:text-white transition-colors"
          title="Toggle state"
        >
          {showSidebar ? "\u276F" : "\u276E"}
        </button>

        {/* State sidebar — Inner World */}
        {showSidebar && (
          <>
            {/* Mobile overlay backdrop */}
            <div
              className="md:hidden fixed inset-0 bg-black/50 z-30"
              onClick={() => setShowSidebar(false)}
            />
            <div className="fixed md:static right-0 top-0 h-full md:h-auto w-72 border-l border-[#1e1e1a] overflow-y-auto bg-[#0a0a0f] z-40">
              <div className="p-4 space-y-5">
                {/* Mobile close button */}
                <div className="md:hidden flex justify-between items-center">
                  <span className="text-xs text-[#737373] uppercase tracking-wider">
                    Inner World
                  </span>
                  <button
                    onClick={() => setShowSidebar(false)}
                    className="text-[#737373] hover:text-white text-lg transition-colors"
                  >
                    &times;
                  </button>
                </div>

                {/* State description */}
                <div className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full animate-pulse"
                    style={{ backgroundColor: getMoodColor(moodValence) }}
                  />
                  <span className="text-sm font-medium">
                    {agentState
                      ? getStateDescription(agentState)
                      : "Loading..."}
                  </span>
                </div>

                {/* Mood word */}
                {agentState && (
                  <div>
                    <span className="text-xs text-[#737373] block mb-1">
                      Mood
                    </span>
                    <span
                      className="text-sm capitalize"
                      style={{ color: getMoodColor(moodValence) }}
                    >
                      {getMoodWord(moodValence, moodArousal)}
                    </span>
                  </div>
                )}

                {/* Energy */}
                <div>
                  <span className="text-xs text-[#737373] block mb-1.5">
                    Energy
                  </span>
                  <div className="h-1.5 bg-[#1e1e1a] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-1000"
                      style={{
                        width: `${energyVal * 100}%`,
                        background: `linear-gradient(90deg, #9a8c7a, #d4a574)`,
                      }}
                    />
                  </div>
                </div>

                {/* Drives */}
                <div className="space-y-2">
                  <span className="text-xs text-[#737373] block">Drives</span>
                  <DriveBar label="Curious" value={curiosityVal} />
                  <DriveBar label="Social" value={socialVal} />
                  <DriveBar label="Expressive" value={expressionVal} />
                  <DriveBar label="Rest need" value={restVal} />
                </div>

                {/* Recent actions */}
                {agentState?.recent_actions &&
                  agentState.recent_actions.length > 0 && (
                    <div>
                      <span className="text-xs text-[#737373] block mb-2">
                        Recent
                      </span>
                      <div className="space-y-1.5">
                        {agentState.recent_actions.slice(0, 5).map((a, i) => (
                          <p key={i} className="text-xs text-[#9a8c7a]">
                            · {formatActionLabel(a.action)}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}

                {/* Actions */}
                <div className="pt-2 border-t border-[#1e1e1a] space-y-2">
                  {/* Rest Now */}
                  <button
                    onClick={() => setSleepConfirm(true)}
                    disabled={sleeping || agentState?.status === "offline"}
                    className="w-full px-3 py-2 bg-[#1a1520]/80 hover:bg-[#252030] border border-[#2a2535] text-sm text-[#b0a0c0] rounded-lg transition-colors disabled:opacity-40"
                  >
                    {sleeping ? "Dreaming..." : "Rest now"}
                  </button>

                  {/* View memories */}
                  <button
                    onClick={() => setShowMemoryPanel(true)}
                    className="w-full px-3 py-2 bg-[#12121a] hover:bg-[#1a1a24] border border-[#262620] text-sm text-[#9a8c7a] rounded-lg transition-colors"
                  >
                    View memories
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Sleep confirmation modal */}
      {sleepConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-sm mx-4">
            <h3 className="text-base font-semibold mb-2">Rest now?</h3>
            <p className="text-sm text-[#a3a3a3] mb-4">
              She&apos;ll enter a sleep cycle. Any queued changes will be
              integrated as dreams.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setSleepConfirm(false)}
                className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleForceSleep}
                className="px-4 py-2 bg-[#6b5b8a] hover:bg-[#7b6b9a] text-white rounded-lg text-sm transition-colors"
              >
                Rest now
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Memory panel */}
      {showMemoryPanel && (
        <MemoryPanel
          agentId={id}
          onClose={() => setShowMemoryPanel(false)}
        />
      )}
    </div>
  );
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="text-center py-2">
        <span className="text-xs text-[#737373] italic">{message.text}</span>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? "bg-[#1a1a24]/70 backdrop-blur-sm text-[#e5e5e5]"
            : "bg-[#1a1510]/70 backdrop-blur-sm text-[#e5e5e0]"
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}

function DriveBar({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  const pct = Math.max(0, Math.min(100, value * 100));
  // Block character visualization
  const filled = Math.round(pct / 20);
  const empty = 5 - filled;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[#9a8c7a] w-20 shrink-0">{label}</span>
      <span className="text-xs font-mono text-[#d4a574]/70 tracking-tight">
        {"▓".repeat(filled)}
        <span className="text-[#525252]">{"░".repeat(empty)}</span>
      </span>
    </div>
  );
}
