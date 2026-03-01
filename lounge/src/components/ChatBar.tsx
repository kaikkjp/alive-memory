"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { ChatMessage } from "@/lib/types";

interface ChatBarProps {
  agentId: string;
  agentName?: string;
  status: "connected" | "reconnecting" | "offline" | "error";
  isSleeping: boolean;
  onSendComplete?: () => void;
}

function formatRelativeTime(timestamp: string): string {
  try {
    const diff = Date.now() - new Date(timestamp).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "now";
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.floor(hrs / 24);
    return `${days}d`;
  } catch {
    return "";
  }
}

export default function ChatBar({
  agentId,
  agentName,
  status,
  isSleeping,
  onSendComplete,
}: ChatBarProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [unread, setUnread] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastActivity = useRef(Date.now());

  // Visitor ID: not needed client-side — the server proxy injects a stable
  // manager-derived ID. We still send it for history lookups (returned by server).
  const visitorId = useRef("");

  const isOffline = status === "offline" || status === "error";

  // Load conversation history on first expand
  const loadHistory = useCallback(async () => {
    if (!visitorId.current || historyLoaded) return;
    try {
      const res = await fetch(`/api/agents/${agentId}/history`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          visitor_id: visitorId.current,
          limit: 100,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.messages && data.messages.length > 0) {
          const restored: ChatMessage[] = data.messages
            .filter((m: { role: string }) => m.role !== "system")
            .map((m: { role: string; text: string; ts: string }) => ({
              role: m.role === "visitor" ? "user" : ("agent" as const),
              text: m.text,
              timestamp: m.ts,
            }));
          setMessages(restored);
        }
      }
    } catch {
      // History load failed silently
    } finally {
      setHistoryLoaded(true);
    }
  }, [agentId, historyLoaded]);

  // Auto-collapse after 5 min inactivity
  const resetIdleTimer = useCallback(() => {
    lastActivity.current = Date.now();
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => {
      setExpanded(false);
    }, 5 * 60 * 1000);
  }, []);

  useEffect(() => {
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    if (expanded) {
      messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, expanded]);

  // Load history on first expand
  useEffect(() => {
    if (expanded && !historyLoaded) {
      loadHistory();
    }
  }, [expanded, historyLoaded, loadHistory]);

  function handleExpand() {
    setExpanded(true);
    setUnread(false);
    resetIdleTimer();
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending || isOffline) return;

    setInput("");
    resetIdleTimer();

    const userMsg: ChatMessage = {
      role: "user",
      text,
      timestamp: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    setSending(true);

    try {
      const res = await fetch(`/api/agents/${agentId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          visitor_id: visitorId.current,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        // Store server-assigned visitor_id for history lookups
        if (data.visitor_id) visitorId.current = data.visitor_id;
        if (data.response) {
          const agentMsg: ChatMessage = {
            role: "agent",
            text: data.response,
            timestamp: data.timestamp || new Date().toISOString(),
          };
          setMessages((m) => [...m, agentMsg]);
          if (!expanded) setUnread(true);
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
      onSendComplete?.();
    }
  }

  // Collapsed: thin input bar
  if (!expanded) {
    return (
      <div className="relative z-20 border-t border-[#1e1e1a]/50 bg-[#0a0a0f]/90 backdrop-blur-sm">
        <form onSubmit={handleSend} className="flex items-center gap-2 px-3 py-2">
          <button
            type="button"
            onClick={handleExpand}
            className="text-[#525252] hover:text-[#9a8c7a] text-xs transition-colors shrink-0"
            title="Expand chat"
          >
            &#x25B2;
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onFocus={handleExpand}
            placeholder={
              isOffline
                ? "She's offline"
                : isSleeping
                  ? "She's dreaming..."
                  : "Say something..."
            }
            className="flex-1 px-3 py-2 bg-[#12121a]/80 border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors disabled:opacity-40"
            disabled={isOffline}
          />
          <button
            type="submit"
            disabled={sending || !input.trim() || isOffline}
            className="px-3 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
          >
            Send
          </button>
          {unread && (
            <span className="absolute top-1 right-4 w-2 h-2 bg-[#d4a574] rounded-full animate-pulse" />
          )}
        </form>
      </div>
    );
  }

  // Expanded: chat history + input
  return (
    <div className="relative z-20 border-t border-[#1e1e1a]/50 bg-[#0a0a0f]/95 backdrop-blur-sm flex flex-col max-h-[50vh] animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#1e1e1a]/30">
        <span className="text-xs text-[#737373]">
          {agentName || (messages.length > 0 ? `${messages.length} messages` : "Chat")}
        </span>
        <button
          onClick={() => setExpanded(false)}
          className="text-[#525252] hover:text-[#9a8c7a] text-xs transition-colors"
        >
          &#x25BC; Collapse
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <p className="text-[#525252] text-xs">
              Send a message to start the conversation
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatBubble key={i} message={msg} />
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="px-4 py-2.5 rounded-2xl bg-[#1e1a14]/70 backdrop-blur-sm">
              <div className="flex gap-1.5">
                <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce" />
                <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce [animation-delay:0.1s]" />
                <div className="w-1.5 h-1.5 bg-[#d4a574]/60 rounded-full animate-bounce [animation-delay:0.2s]" />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEnd} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="border-t border-[#1e1e1a]/30 px-4 py-2.5 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            resetIdleTimer();
          }}
          placeholder={
            isOffline
              ? "She's offline"
              : isSleeping
                ? "She's dreaming..."
                : "Say something..."
          }
          className="flex-1 px-3 py-2 bg-[#12121a]/80 border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-colors disabled:opacity-40"
          disabled={sending || isOffline}
        />
        <button
          type="submit"
          disabled={sending || !input.trim() || isOffline}
          className="px-4 py-2 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="text-center py-1">
        <span className="text-xs text-[#737373] italic">{message.text}</span>
      </div>
    );
  }

  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? "bg-[#1e1e30]/70 backdrop-blur-sm text-[#e5e5e5]"
            : "bg-[#1e1a14]/70 backdrop-blur-sm text-[#e5e5e0]"
        }`}
      >
        {message.text}
      </div>
      {message.timestamp && (
        <span className="text-[10px] text-[#3a3a3a] mt-1 px-1">
          {formatRelativeTime(message.timestamp)}
        </span>
      )}
    </div>
  );
}
