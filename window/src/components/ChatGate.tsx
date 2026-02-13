'use client';

import { useCallback, useState } from 'react';

interface ChatGateProps {
  onAuthenticated: (token: string) => void;
}

/**
 * "Enter the shop" button + token input modal.
 * Invalid tokens show "The door doesn't open." — no error codes.
 */
export default function ChatGate({ onAuthenticated }: ChatGateProps) {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [validating, setValidating] = useState(false);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!token.trim() || validating) return;

      setValidating(true);
      setError('');

      try {
        const res = await fetch(`${apiBase}/api/validate-token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: token.trim() }),
        });

        if (res.ok) {
          localStorage.setItem('shopkeeper-token', token.trim());
          onAuthenticated(token.trim());
        } else {
          setError('The door doesn\u2019t open.');
        }
      } catch {
        setError('The door doesn\u2019t open.');
      } finally {
        setValidating(false);
      }
    },
    [token, validating, apiBase, onAuthenticated],
  );

  if (!open) {
    return (
      <button
        className="chat-gate__enter"
        onClick={() => setOpen(true)}
      >
        Enter the shop &rarr;
      </button>
    );
  }

  return (
    <div className="chat-gate__modal">
      <form onSubmit={handleSubmit} className="chat-gate__form">
        <p className="chat-gate__prompt">Present your invitation.</p>
        <input
          type="text"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Token"
          className="chat-gate__input"
          autoFocus
          disabled={validating}
        />
        {error && <p className="chat-gate__error">{error}</p>}
        <div className="chat-gate__actions">
          <button
            type="submit"
            className="chat-gate__submit"
            disabled={validating || !token.trim()}
          >
            {validating ? '...' : 'Enter'}
          </button>
          <button
            type="button"
            className="chat-gate__cancel"
            onClick={() => {
              setOpen(false);
              setError('');
              setToken('');
            }}
          >
            Leave
          </button>
        </div>
      </form>
    </div>
  );
}
