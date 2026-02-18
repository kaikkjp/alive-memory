'use client';

import { useEffect, useRef, useState } from 'react';
import { SPRITE_MAP, DEFAULT_EXPRESSION } from '@/lib/config';

interface CharacterSpriteProps {
  expression: string;
  hidden?: boolean;
}

/**
 * Expression-driven character sprite with crossfade transitions.
 * Preloads all expression sprites on mount for instant crossfades.
 */
export default function CharacterSprite({ expression, hidden }: CharacterSpriteProps) {
  const [prevExpression, setPrevExpression] = useState<string | null>(null);
  const [activeExpression, setActiveExpression] = useState(expression);
  const [opacity, setOpacity] = useState(1);
  const transitionRef = useRef<number>(undefined);

  // Preload all sprites on mount
  useEffect(() => {
    Object.values(SPRITE_MAP).forEach((file) => {
      const img = new Image();
      img.src = `/assets/sprites/${file}`;
    });
  }, []);

  // Handle expression changes with crossfade
  useEffect(() => {
    if (expression === activeExpression) return;

    if (transitionRef.current) cancelAnimationFrame(transitionRef.current);

    setPrevExpression(activeExpression);
    setActiveExpression(expression);
    setOpacity(0);

    const startTime = performance.now();
    const duration = 900; // matches --sprite-crossfade

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = progress < 0.5
        ? 2 * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 2) / 2;

      setOpacity(eased);

      if (progress < 1) {
        transitionRef.current = requestAnimationFrame(animate);
      } else {
        setPrevExpression(null);
      }
    };

    transitionRef.current = requestAnimationFrame(animate);

    return () => {
      if (transitionRef.current) cancelAnimationFrame(transitionRef.current);
    };
  }, [expression]); // eslint-disable-line react-hooks/exhaustive-deps

  const spriteFile = SPRITE_MAP[activeExpression] || SPRITE_MAP[DEFAULT_EXPRESSION];
  const prevFile = prevExpression
    ? SPRITE_MAP[prevExpression] || SPRITE_MAP[DEFAULT_EXPRESSION]
    : null;

  if (hidden) return null;

  return (
    <div className="character-sprite">
      {/* Previous sprite (fading out) */}
      {prevFile && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={`/assets/sprites/${prevFile}`}
          alt=""
          draggable={false}
          className="character-sprite__img"
          style={{
            position: 'absolute',
            opacity: 1 - opacity,
          }}
        />
      )}

      {/* Active sprite (fading in) */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/assets/sprites/${spriteFile}`}
        alt=""
        draggable={false}
        className="character-sprite__img"
        style={{ opacity }}
      />
    </div>
  );
}
