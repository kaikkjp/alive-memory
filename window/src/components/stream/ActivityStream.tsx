'use client';

import type { Fragment as FragmentData } from '@/lib/types';
import FragmentItem from './Fragment';

interface ActivityStreamProps {
  fragments: FragmentData[];
}

/**
 * Floating text fragments from the shopkeeper's inner life.
 * Newest at the bottom (column-reverse), older entries fade via CSS mask.
 */
export default function ActivityStream({ fragments }: ActivityStreamProps) {
  return (
    <div className="activity-stream">
      {fragments.map((frag) => (
        <FragmentItem key={frag.id} fragment={frag} />
      ))}
    </div>
  );
}
