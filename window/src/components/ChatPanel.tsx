'use client';

import { useCallback, useRef, useState } from 'react';

interface ChatPanelProps {
  token: string;
  sendChat: (text: string, token: string) => void;
  onClose: () => void;
}

/**
 * Slide-up chat panel. Bottom 40% of the viewport, scene shrinks above.
 */
export default function ChatPanel({
  token,
  sendChat,
  onClose,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    sendChat(text, token);
    setInput('');
    inputRef.current?.focus();
  }, [input, token, sendChat]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleClose = useCallback(() => {
    sendChat('Thank you for visiting.', token);
    onClose();
  }, [token, sendChat, onClose]);

  return (
    <div className="chat-panel">
      <div className="chat-panel__header">
        <span className="chat-panel__title">Visiting</span>
        <button className="chat-panel__close" onClick={handleClose}>
          Leave
        </button>
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
          autoFocus
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
