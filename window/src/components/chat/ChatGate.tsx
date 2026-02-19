'use client';

import { useDelayedReveal } from '@/hooks/useDelayedReveal';

interface ChatGateProps {
  onEnter: () => void;
  sleeping: boolean;
}

/**
 * "Enter the shop →" button. Appears after a configurable delay.
 * Hidden while the shopkeeper sleeps — you can't enter when she's asleep.
 */
export default function ChatGate({ onEnter, sleeping }: ChatGateProps) {
  const visible = useDelayedReveal(3000); // short pause before button appears

  if (!visible || sleeping) return null;

  return (
    <div className="chat-gate">
      <button className="chat-gate__enter" onClick={onEnter}>
        Enter the shop &rarr;
      </button>
    </div>
  );
}
