'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage } from '@/lib/types';
import ChatMessageItem from './ChatMessage';

interface ChatPanelProps {
  open: boolean;
  messages: ChatMessage[];
  displayName: string;
  onSend: (text: string) => boolean;
  onClose: () => void;
}

/**
 * Slide-up chat panel. Scene stays visible above.
 * Messages scroll to bottom automatically on new entries.
 */
export default function ChatPanel({
  open,
  messages,
  displayName,
  onSend,
  onClose,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    const sent = onSend(text);
    // Only clear the input if the message was actually sent.
    // If WS was closed, preserve the text so the user can retry.
    if (sent) setInput('');
    inputRef.current?.focus();
  }, [input, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className={`chat-panel ${open ? 'chat-panel--open' : ''}`}>
      <div className="chat-panel__header">
        <span className="chat-panel__title">
          Visiting as {displayName}
        </span>
        <button className="chat-panel__close" onClick={onClose}>
          Leave
        </button>
      </div>

      <div className="chat-panel__messages">
        {messages.map((msg) => (
          <ChatMessageItem key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-panel__input-area">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Say something..."
          className="chat-panel__input"
        />
        <button
          className="chat-panel__send"
          onClick={handleSend}
          disabled={!input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
