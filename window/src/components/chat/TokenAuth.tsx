'use client';

import { useCallback, useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

interface TokenAuthProps {
  onValidated: (token: string, displayName: string) => void;
  onCancel: () => void;
}

/**
 * Token input gate. Visitor enters their invitation token.
 * Validation happens via HTTP POST to /api/validate-token.
 */
export default function TokenAuth({ onValidated, onCancel }: TokenAuthProps) {
  const [token, setToken] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!token.trim() || validating) return;
      setValidating(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE}/api/validate-token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: token.trim() }),
        });
        const body = await res.json();
        if (res.ok && body.valid) {
          sessionStorage.setItem('shopkeeper-visitor-token', token.trim());
          onValidated(token.trim(), body.display_name || 'Visitor');
        } else {
          setError("The door doesn\u2019t open.");
        }
      } catch {
        setError('Could not reach the shop. Try again.');
      } finally {
        setValidating(false);
      }
    },
    [token, validating, onValidated],
  );

  return (
    <div className="token-auth">
      <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
        <p className="token-auth__prompt">Present your invitation.</p>
        <input
          type="text"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Token"
          className="token-auth__input"
          autoFocus
          disabled={validating}
        />
        {error && <p className="token-auth__error">{error}</p>}
        <div className="token-auth__actions">
          <button
            type="submit"
            className="token-auth__submit"
            disabled={validating || !token.trim()}
          >
            {validating ? '\u2026' : 'Enter'}
          </button>
          <button
            type="button"
            className="token-auth__cancel"
            onClick={onCancel}
          >
            Leave
          </button>
        </div>
      </form>
    </div>
  );
}
