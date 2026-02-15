'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { SceneLayers, SpriteState, TimeOfDay } from '@/lib/types';
import {
  getAssetUrl,
  drawImage,
  drawImageAt,
  preloadImages,
} from '@/lib/compositor';
import { useParticles } from '@/hooks/useParticles';
import {
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
  CHARACTER_X_PCT,
  CHARACTER_Y_PCT,
  CHARACTER_HEIGHT_PCT,
  COLOR_GRADE_RED,
  COLOR_GRADE_BLUE,
  SHADOW_OFFSET_X,
  SHADOW_OFFSET_Y,
  SHADOW_OPACITY,
  SHADOW_BLUR,
  SPRITE_CROSSFADE_MS,
  SPRITE_MAP,
  SCENERY_GRADIENTS,
  Z_INDEX,
  DEFAULT_SPRITE_STATE,
  DEFAULT_TIME_OF_DAY,
} from '@/lib/scene-constants';

interface SceneCanvasProps {
  /** Sprite state for the new 6-layer compositor. */
  spriteState?: SpriteState;
  /** Time of day for outdoor scenery layer. */
  timeOfDay?: TimeOfDay;
  /** Legacy: active scene layers from pipeline. */
  activeLayers?: SceneLayers | null;
  /** Legacy: previous layers for crossfade. */
  prevLayers?: SceneLayers | null;
  /** Legacy: crossfade opacity (0-1). */
  opacity?: number;
  /** Weather type for particle effects. */
  weather?: string;
}

/**
 * 6-layer scene compositor.
 *
 * Layer stack (bottom to top):
 *   0: Outdoor scenery (gradient fallback or image)
 *   1: Shop interior
 *   2: Character sprite (with drop shadow + crossfade)
 *   3: Counter foreground (occludes character below 72%)
 *   4: CSS vignette
 *   5: Dust particles (canvas)
 *
 * When `activeLayers` is provided (legacy pipeline mode), the component
 * falls back to the original canvas-based rendering for backward compat.
 */
export default function SceneCanvas({
  spriteState,
  timeOfDay,
  activeLayers,
  prevLayers,
  opacity = 1,
  weather = '',
}: SceneCanvasProps) {
  // Use legacy mode when activeLayers provided and no explicit spriteState
  const useLegacy = !spriteState && !!activeLayers;

  if (useLegacy) {
    return (
      <LegacySceneCanvas
        activeLayers={activeLayers!}
        prevLayers={prevLayers ?? null}
        opacity={opacity}
        weather={weather}
      />
    );
  }

  return (
    <CompositorCanvas
      spriteState={spriteState ?? DEFAULT_SPRITE_STATE}
      timeOfDay={timeOfDay ?? DEFAULT_TIME_OF_DAY}
      weather={weather}
    />
  );
}

// ─── New 6-layer compositor ───

interface CompositorCanvasProps {
  spriteState: SpriteState;
  timeOfDay: TimeOfDay;
  weather: string;
}

function CompositorCanvas({
  spriteState,
  timeOfDay,
  weather,
}: CompositorCanvasProps) {
  const dustCanvasRef = useRef<HTMLCanvasElement>(null);
  const [prevSprite, setPrevSprite] = useState<SpriteState | null>(null);
  const [activeSprite, setActiveSprite] = useState(spriteState);
  const [spriteOpacity, setSpriteOpacity] = useState(1);
  const transitionRef = useRef<number>(undefined);

  // Handle sprite state changes with crossfade
  useEffect(() => {
    if (spriteState === activeSprite) return;

    // Cancel any in-progress transition
    if (transitionRef.current) cancelAnimationFrame(transitionRef.current);

    setPrevSprite(activeSprite);
    setActiveSprite(spriteState);
    setSpriteOpacity(0);

    const startTime = performance.now();

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / SPRITE_CROSSFADE_MS, 1);
      // Ease in-out
      const eased =
        progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;

      setSpriteOpacity(eased);

      if (progress < 1) {
        transitionRef.current = requestAnimationFrame(animate);
      } else {
        setPrevSprite(null);
      }
    };

    transitionRef.current = requestAnimationFrame(animate);

    return () => {
      if (transitionRef.current) cancelAnimationFrame(transitionRef.current);
    };
  }, [spriteState]); // eslint-disable-line react-hooks/exhaustive-deps

  // Dust particle system
  useParticles(dustCanvasRef, weather || 'clear', CANVAS_WIDTH, CANVAS_HEIGHT);

  const spriteFile = SPRITE_MAP[activeSprite];
  const prevSpriteFile = prevSprite ? SPRITE_MAP[prevSprite] : null;
  const sceneryGradient = SCENERY_GRADIENTS[timeOfDay];

  const charStyle: React.CSSProperties = {
    position: 'absolute',
    left: `${CHARACTER_X_PCT * 100}%`,
    top: `${CHARACTER_Y_PCT * 100}%`,
    height: `${CHARACTER_HEIGHT_PCT * 100}%`,
    width: 'auto',
    filter: `url(#scene-color-grade) drop-shadow(${SHADOW_OFFSET_X}px ${SHADOW_OFFSET_Y}px ${SHADOW_BLUR}px rgba(0,0,0,${SHADOW_OPACITY}))`,
    zIndex: Z_INDEX.CHARACTER,
  };

  return (
    <div
      className="scene-canvas-container"
      style={{
        position: 'relative',
        width: '100%',
        aspectRatio: '3/2',
        overflow: 'hidden',
        backgroundColor: '#0a0a0c',
      }}
    >
      {/* SVG filter for character color grading (per-channel multiplication) */}
      <svg width="0" height="0" style={{ position: 'absolute' }}>
        <defs>
          <filter id="scene-color-grade">
            <feColorMatrix
              type="matrix"
              values={`${COLOR_GRADE_RED} 0 0 0 0  0 1 0 0 0  0 0 ${COLOR_GRADE_BLUE} 0 0  0 0 0 1 0`}
            />
          </filter>
        </defs>
      </svg>
      {/* Layer 0: Outdoor scenery */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          zIndex: Z_INDEX.SCENERY,
          background: sceneryGradient,
        }}
      />

      {/* Layer 1: Shop interior */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/assets/shop_interior.png"
        alt=""
        draggable={false}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          zIndex: Z_INDEX.SHOP_INTERIOR,
        }}
      />

      {/* Layer 2: Character sprite (previous — fading out) */}
      {prevSpriteFile && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={`/assets/sprites/${prevSpriteFile}`}
          alt=""
          draggable={false}
          style={{
            ...charStyle,
            opacity: 1 - spriteOpacity,
          }}
        />
      )}

      {/* Layer 2: Character sprite (active — fading in) */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/assets/sprites/${spriteFile}`}
        alt=""
        draggable={false}
        style={{
          ...charStyle,
          opacity: spriteOpacity,
        }}
      />

      {/* Layer 3: Counter foreground */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/assets/counter_foreground.png"
        alt=""
        draggable={false}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          zIndex: Z_INDEX.COUNTER,
          pointerEvents: 'none',
        }}
      />

      {/* Layer 4: Vignette */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          zIndex: Z_INDEX.VIGNETTE,
          background:
            'radial-gradient(ellipse at center, transparent 35%, rgba(8,6,4,0.65) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* Layer 5: Dust particles */}
      <canvas
        ref={dustCanvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          zIndex: Z_INDEX.DUST,
          pointerEvents: 'none',
        }}
      />
    </div>
  );
}

// ─── Legacy canvas-based renderer (backward compat) ───

interface LegacySceneCanvasProps {
  activeLayers: SceneLayers;
  prevLayers: SceneLayers | null;
  opacity: number;
  weather: string;
}

function LegacySceneCanvas({
  activeLayers,
  prevLayers,
  opacity,
  weather,
}: LegacySceneCanvasProps) {
  const activeCanvasRef = useRef<HTMLCanvasElement>(null);
  const prevCanvasRef = useRef<HTMLCanvasElement>(null);
  const particleCanvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const urls = getLayerUrls(activeLayers);
    preloadImages(urls);
  }, [activeLayers]);

  const drawScene = useCallback(
    async (
      canvas: HTMLCanvasElement | null,
      layers: SceneLayers | null,
    ) => {
      if (!canvas || !layers) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      await drawImage(ctx, getAssetUrl('bg', layers.background));
      await drawImage(ctx, getAssetUrl('shop', layers.shop));
      for (const item of layers.items) {
        await drawImageAt(
          ctx,
          getAssetUrl('items', item.sprite),
          item.x,
          item.y,
          item.width,
          item.height,
        );
      }
      const pos = layers.character_position;
      await drawImageAt(
        ctx,
        getAssetUrl('her', layers.character),
        pos.x,
        pos.y,
        pos.width,
        pos.height,
      );
      for (const fg of layers.foreground) {
        await drawImage(ctx, getAssetUrl('fg', fg));
      }
    },
    [],
  );

  useEffect(() => {
    drawScene(activeCanvasRef.current, activeLayers);
  }, [activeLayers, drawScene]);

  useEffect(() => {
    drawScene(prevCanvasRef.current, prevLayers);
  }, [prevLayers, drawScene]);

  useParticles(particleCanvasRef, weather, CANVAS_WIDTH, CANVAS_HEIGHT);

  return (
    <div
      className="scene-canvas-container"
      style={{ position: 'relative', width: '100%', aspectRatio: '3/2' }}
    >
      {prevLayers && (
        <canvas
          ref={prevCanvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            opacity: 1 - opacity,
          }}
        />
      )}
      <canvas
        ref={activeCanvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          opacity: opacity,
        }}
      />
      <canvas
        ref={particleCanvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
}

function getLayerUrls(layers: SceneLayers): string[] {
  const urls: string[] = [
    getAssetUrl('bg', layers.background),
    getAssetUrl('shop', layers.shop),
    getAssetUrl('her', layers.character),
  ];
  for (const item of layers.items) {
    urls.push(getAssetUrl('items', item.sprite));
  }
  for (const fg of layers.foreground) {
    urls.push(getAssetUrl('fg', fg));
  }
  return urls;
}
