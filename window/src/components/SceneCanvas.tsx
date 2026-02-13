'use client';

import { useCallback, useEffect, useRef } from 'react';
import type { SceneLayers } from '@/lib/types';
import {
  getAssetUrl,
  drawImage,
  drawImageAt,
  preloadImages,
} from '@/lib/compositor';
import { useParticles } from '@/hooks/useParticles';

const CANVAS_WIDTH = 1536;
const CANVAS_HEIGHT = 1024;

interface SceneCanvasProps {
  activeLayers: SceneLayers | null;
  prevLayers: SceneLayers | null;
  opacity: number;
  weather: string;
}

/**
 * Canvas compositor that renders the layered scene.
 * Two offscreen canvases enable crossfade transitions.
 * A separate transparent overlay handles particle effects.
 */
export default function SceneCanvas({
  activeLayers,
  prevLayers,
  opacity,
  weather,
}: SceneCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeCanvasRef = useRef<HTMLCanvasElement>(null);
  const prevCanvasRef = useRef<HTMLCanvasElement>(null);
  const particleCanvasRef = useRef<HTMLCanvasElement>(null);

  // Preload images when layers change
  useEffect(() => {
    if (!activeLayers) return;
    const urls = getLayerUrls(activeLayers);
    preloadImages(urls);
  }, [activeLayers]);

  // Draw active scene layers
  const drawScene = useCallback(
    async (
      canvas: HTMLCanvasElement | null,
      layers: SceneLayers | null,
    ) => {
      if (!canvas || !layers) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

      // Layer 1: Background
      await drawImage(ctx, getAssetUrl('bg', layers.background));

      // Layer 2: Shop interior
      await drawImage(ctx, getAssetUrl('shop', layers.shop));

      // Layer 3: Shelf items
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

      // Layer 4: Character
      const pos = layers.character_position;
      await drawImageAt(
        ctx,
        getAssetUrl('her', layers.character),
        pos.x,
        pos.y,
        pos.width,
        pos.height,
      );

      // Layer 5: Foreground overlays
      for (const fg of layers.foreground) {
        await drawImage(ctx, getAssetUrl('fg', fg));
      }
    },
    [],
  );

  // Redraw when layers or opacity change
  useEffect(() => {
    drawScene(activeCanvasRef.current, activeLayers);
  }, [activeLayers, drawScene]);

  useEffect(() => {
    drawScene(prevCanvasRef.current, prevLayers);
  }, [prevLayers, drawScene]);

  // Particle system on overlay canvas
  useParticles(particleCanvasRef, weather, CANVAS_WIDTH, CANVAS_HEIGHT);

  return (
    <div
      ref={containerRef}
      className="scene-canvas-container"
      style={{ position: 'relative', width: '100%', aspectRatio: '3/2' }}
    >
      {/* Previous scene (fading out) */}
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

      {/* Active scene (fading in) */}
      <canvas
        ref={activeCanvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          opacity: activeLayers ? opacity : 0,
        }}
      />

      {/* Particle overlay */}
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
