'use client';

interface ConnectionPulseProps {
  connected: boolean;
}

/**
 * WebSocket status indicator — green pulse = connected, amber = reconnecting.
 */
export default function ConnectionPulse({ connected }: ConnectionPulseProps) {
  return (
    <span
      className={`connection-pulse ${connected ? 'connection-pulse--live' : 'connection-pulse--amber'}`}
      title={connected ? 'Connected' : 'Reconnecting\u2026'}
    />
  );
}
