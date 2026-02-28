/** Scene composition constants derived from scene-config.json.
 *  All positioning is percentage-based for responsive scaling.
 *  No raw pixel values in components — reference these constants instead.
 */

import type { SpriteState, TimeOfDay } from './types';

// ─── Canvas dimensions ───

export const CANVAS_WIDTH = 1536;
export const CANVAS_HEIGHT = 1024;

// ─── Character positioning (percentage of canvas) ───

export const CHARACTER_X_PCT = 0.39;
export const CHARACTER_Y_PCT = 0.21;
export const CHARACTER_HEIGHT_PCT = 0.55;

// ─── Counter foreground ───

export const COUNTER_CUT_PCT = 0.72;
export const COUNTER_FADE_PX = 6;

// ─── Vignette ───

export const VIGNETTE_CENTER_PCT = 0.35;
export const VIGNETTE_EDGE_COLOR = 'rgba(8,6,4,0.65)';

// ─── Dust particles ───

export const DUST_COUNT = 35;
export const DUST_COLOR = 'rgba(255,210,150)';
export const DUST_MAX_OPACITY = 0.3;

// ─── Color grade (CSS filter channel multipliers) ───

export const COLOR_GRADE_RED = 1.05;
export const COLOR_GRADE_BLUE = 0.92;

// ─── Character shadow ───

export const SHADOW_OFFSET_X = 5;
export const SHADOW_OFFSET_Y = 5;
export const SHADOW_OPACITY = 0.3;
export const SHADOW_BLUR = 6;

// ─── Sprite crossfade ───

export const SPRITE_CROSSFADE_MS = 300;

// ─── Layer z-index ordering ───

export const Z_INDEX = {
  SCENERY: 0,
  SHOP_INTERIOR: 1,
  CHARACTER: 2,
  COUNTER: 3,
  VIGNETTE: 4,
  DUST: 5,
} as const;

// ─── Sprite file map ───

export const SPRITE_MAP: Record<SpriteState, string> = {
  engaged: 'char-1-cropped.png',
  tired: 'char-2-cropped.png',
  thinking: 'char-3-cropped.png',
  curious: 'char-4-cropped.png',
  surprised: 'char-5-cropped.png',
  focused: 'char-6-cropped.png',
  smiling: 'char-1-cropped.png',
};

// ─── Scenery gradient fallbacks (when PNG assets not available) ───

export const SCENERY_GRADIENTS: Record<TimeOfDay, string> = {
  morning:
    'linear-gradient(180deg, #87CEEB 0%, #FFE4B5 40%, #FFDAB9 70%, #E8DCC8 100%)',
  afternoon:
    'linear-gradient(180deg, #4A90D9 0%, #87CEEB 40%, #B0C4DE 70%, #D4CFC4 100%)',
  evening:
    'linear-gradient(180deg, #2C1654 0%, #C2544E 30%, #E8956A 55%, #D4A574 100%)',
  night:
    'linear-gradient(180deg, #0A0E1A 0%, #1A1F3A 40%, #2A2540 70%, #1E1A2E 100%)',
};

// ─── Default state ───

export const DEFAULT_SPRITE_STATE: SpriteState = 'thinking';
export const DEFAULT_TIME_OF_DAY: TimeOfDay = 'afternoon';
