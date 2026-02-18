'use client';

import { useRef } from 'react';
import { useParticles } from '@/hooks/useParticles';

interface DustParticlesProps {
  weather?: string;
}

/**
 * Canvas-based particle overlay for dust motes, rain, and snow.
 * Uses requestAnimationFrame for smooth animation.
 */
export default function DustParticles({ weather = 'clear' }: DustParticlesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Canvas size matches viewport — actual pixel dimensions set dynamically
  useParticles(canvasRef, weather, 1536, 1024);

  return (
    <canvas
      ref={canvasRef}
      width={1536}
      height={1024}
      className="dust-canvas"
    />
  );
}
