'use client';

import { useEffect, useState } from 'react';

/**
 * Returns true after `delayMs` milliseconds.
 * Used for time-delayed element appearance (e.g. "Enter the shop" button).
 */
export function useDelayedReveal(delayMs: number): boolean {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  return visible;
}
