'use client';

interface SleepOverlayProps {
  sleeping: boolean;
}

/**
 * Dark blue-tinted overlay when the shopkeeper is sleeping.
 * Transitions slowly (3s) for a natural day/night feel.
 */
export default function SleepOverlay({ sleeping }: SleepOverlayProps) {
  return (
    <div
      className="sleep-overlay"
      style={{ opacity: sleeping ? 1 : 0 }}
    />
  );
}
