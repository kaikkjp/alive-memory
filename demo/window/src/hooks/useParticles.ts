'use client';

import { useCallback, useEffect, useRef } from 'react';
import {
  createParticleSystem,
  updateParticles,
  drawParticles,
  type ParticleSystem,
} from '@/lib/particles';

/**
 * Hook that runs particle effects on a canvas overlay.
 * Always renders dust motes; adds rain or snow based on weather.
 */
export function useParticles(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  weather: string,
  width: number,
  height: number,
) {
  const systemsRef = useRef<ParticleSystem[]>([]);
  const animFrameRef = useRef<number>(undefined);

  // Rebuild particle systems when weather changes
  useEffect(() => {
    const systems: ParticleSystem[] = [
      createParticleSystem('dust', width, height),
    ];

    if (weather === 'rain' || weather === 'storm') {
      systems.push(createParticleSystem('rain', width, height));
    } else if (weather === 'snow') {
      systems.push(createParticleSystem('snow', width, height));
    }

    systemsRef.current = systems;
  }, [weather, width, height]);

  const animate = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, width, height);

    for (const system of systemsRef.current) {
      updateParticles(system, width, height);
      drawParticles(ctx, system);
    }

    animFrameRef.current = requestAnimationFrame(animate);
  }, [canvasRef, width, height]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(animate);
    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [animate]);
}
