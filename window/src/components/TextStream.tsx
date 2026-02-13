'use client';

import { useEffect, useRef, useState } from 'react';
import type { TextEntry, FragmentType } from '@/lib/types';

interface TextStreamProps {
  entries: TextEntry[];
  currentThought: string;
}

/**
 * Scrolling vertical feed of the shopkeeper's thoughts, journal entries,
 * and dialogue. Newer entries appear at the top with a typewriter reveal.
 */
export default function TextStream({
  entries,
  currentThought,
}: TextStreamProps) {
  return (
    <div className="text-stream">
      {currentThought && (
        <div className="text-entry text-entry--thought text-entry--current">
          <TypewriterText text={currentThought} />
        </div>
      )}
      {entries.map((entry, i) => (
        <div
          key={entry.timestamp + i}
          className={`text-entry text-entry--${entry.type}`}
          style={{ opacity: getEntryOpacity(i) }}
        >
          <TypewriterText text={entry.content} />
          <span className="text-entry__time">{formatRelativeTime(entry.timestamp)}</span>
        </div>
      ))}
    </div>
  );
}

function TypewriterText({ text }: { text: string }) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);
  const textRef = useRef(text);

  useEffect(() => {
    // Reset if text changes
    if (textRef.current !== text) {
      textRef.current = text;
      setDisplayed('');
      setDone(false);
    }

    if (done) return;

    let i = displayed.length;
    if (i >= text.length) {
      setDone(true);
      return;
    }

    const timer = setTimeout(() => {
      setDisplayed(text.slice(0, i + 1));
    }, 30);

    return () => clearTimeout(timer);
  }, [text, displayed, done]);

  return <span>{displayed}{!done && <span className="typewriter-cursor">|</span>}</span>;
}

/** Older entries progressively fade. */
function getEntryOpacity(index: number): number {
  if (index <= 2) return 1;
  if (index <= 5) return 0.7;
  return 0.4;
}

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diff = now - then;

  if (Number.isNaN(diff) || diff < 0) return '';

  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
