'use client';

import { useMemo } from 'react';
import { SPRITE_MAP, DEFAULT_EXPRESSION } from '@/lib/config';

interface BodyOutput {
  expression_hint?: string;
  gaze?: string;
  posture?: string;
}

/**
 * Maps ALIVE body output to a sprite key.
 * Priority: expression_hint > gaze > posture > default.
 * Unknown keys fall back to "thinking".
 */
export function useExpression(
  spriteState?: string,
  body?: BodyOutput | null,
): string {
  return useMemo(() => {
    // If we have a direct sprite_state from the backend, use it
    if (spriteState && SPRITE_MAP[spriteState]) {
      return spriteState;
    }

    // If we have body output, map it
    if (body) {
      if (body.expression_hint && SPRITE_MAP[body.expression_hint]) {
        return body.expression_hint;
      }
      if (body.gaze === 'at_visitor') return 'curious';
      if (body.gaze === 'down' || body.gaze === 'away') return 'thinking';
      if (body.posture === 'leaning_forward') return 'smiling';
    }

    return DEFAULT_EXPRESSION;
  }, [spriteState, body]);
}
