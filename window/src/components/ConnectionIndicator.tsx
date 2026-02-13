'use client';

interface ConnectionIndicatorProps {
  connected: boolean;
}

/**
 * Subtle pulse dot in the corner indicating live WebSocket connection.
 * Green pulse = connected, faded = disconnected.
 */
export default function ConnectionIndicator({
  connected,
}: ConnectionIndicatorProps) {
  return (
    <div
      className={`connection-indicator ${connected ? 'connection-indicator--live' : 'connection-indicator--offline'}`}
      title={connected ? 'Connected' : 'Reconnecting...'}
    >
      <span className="connection-indicator__dot" />
    </div>
  );
}
