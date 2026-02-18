'use client';

import type { Fragment as FragmentData } from '@/lib/types';

interface FragmentProps {
  fragment: FragmentData;
}

/**
 * Individual text fragment in the activity stream.
 * Styled by fragment type — thoughts, journal entries, actions, speech.
 */
export default function FragmentItem({ fragment }: FragmentProps) {
  return (
    <div className={`fragment fragment--${fragment.type}`}>
      {fragment.content}
    </div>
  );
}
