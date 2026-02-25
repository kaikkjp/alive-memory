"use client";

import { useState, useRef, useEffect, use } from "react";
import Link from "next/link";
import AgentNav from "@/components/AgentNav";

interface Message {
  role: "user" | "agent" | "system";
  text: string;
  timestamp: string;
}

interface AgentState {
  status: string;
  mood?: { valence: number; arousal: number };
  energy?: number;
  engaged?: boolean;
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
  const messagesEnd = useRef<HTMLDivElement>(null);
  const visitorId = useRef(`lounge-${Date.now()}`);

  // Poll agent state
  useEffect(() => {
    fetchState();
    const interval = setInterval(fetchState, 30000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function fetchState() {
    try {
      const res = await fetch(`/api/agents/${id}/status`);
      if (res.ok) setAgentState(await res.json());
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
      // Chat via portal proxy (uses first API key internally)
      const res = await fetch(`/api/agents/${id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          visitor_id: visitorId.current,
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

  return (
    <div className="flex flex-col h-screen">
      <AgentNav agentId={id} active="lounge" />

      <div className="flex flex-1 overflow-hidden">
        {/* Chat panel */}
        <div className="flex-1 flex flex-col">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full">
                <p className="text-[#737373] text-sm">
                  Send a message to start the conversation
                </p>
              </div>
            )}
            {messages.map((msg, i) => (
              <ChatBubble key={i} message={msg} />
            ))}
            {sending && (
              <div className="flex gap-1 px-4 py-2">
                <div className="w-2 h-2 bg-[#737373] rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-[#737373] rounded-full animate-bounce [animation-delay:0.1s]" />
                <div className="w-2 h-2 bg-[#737373] rounded-full animate-bounce [animation-delay:0.2s]" />
              </div>
            )}
            <div ref={messagesEnd} />
          </div>

          {/* Input */}
          <form
            onSubmit={handleSend}
            className="border-t border-[#262626] px-4 py-3 flex gap-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a message..."
              className="flex-1 px-4 py-2.5 bg-[#141414] border border-[#262626] rounded-lg text-sm focus:outline-none focus:border-[#3b82f6] transition-colors"
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="px-4 py-2.5 bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              Send
            </button>
          </form>
        </div>

        {/* State sidebar (collapsible) */}
        <button
          onClick={() => setShowSidebar(!showSidebar)}
          className="hidden md:flex items-center px-1 border-l border-[#262626] text-[#737373] hover:text-white transition-colors"
          title="Toggle agent state"
        >
          {showSidebar ? "\u276F" : "\u276E"}
        </button>

        {showSidebar && agentState && (
          <div className="hidden md:block w-64 border-l border-[#262626] p-4 overflow-y-auto">
            <h3 className="text-xs font-semibold uppercase text-[#737373] mb-3">
              Agent State
            </h3>
            <div className="space-y-3 text-sm">
              <StateRow
                label="Status"
                value={agentState.status}
                color={
                  agentState.status === "active"
                    ? "text-[#22c55e]"
                    : "text-[#ef4444]"
                }
              />
              {agentState.mood && (
                <>
                  <DriveBar
                    label="Valence"
                    value={agentState.mood.valence}
                    min={-1}
                    max={1}
                  />
                  <DriveBar
                    label="Arousal"
                    value={agentState.mood.arousal}
                    min={0}
                    max={1}
                  />
                </>
              )}
              {agentState.energy !== undefined && (
                <DriveBar label="Energy" value={agentState.energy} min={0} max={1} />
              )}
              {agentState.engaged !== undefined && (
                <StateRow
                  label="Engaged"
                  value={agentState.engaged ? "Yes" : "No"}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="text-center">
        <span className="text-xs text-[#737373] italic">{message.text}</span>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] px-4 py-2.5 rounded-2xl text-sm ${
          isUser
            ? "bg-[#3b82f6] text-white"
            : "bg-[#1e1e1e] text-[#e5e5e5]"
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}

function StateRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="flex justify-between">
      <span className="text-[#737373]">{label}</span>
      <span className={color || ""}>{value}</span>
    </div>
  );
}

function DriveBar({
  label,
  value,
  min,
  max,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-[#737373]">{label}</span>
        <span>{value.toFixed(2)}</span>
      </div>
      <div className="h-1.5 bg-[#262626] rounded-full overflow-hidden">
        <div
          className="h-full bg-[#3b82f6] rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
    </div>
  );
}
