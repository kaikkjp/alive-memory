'use client';

import { useEffect, useRef, useState } from 'react';
import type { SceneLayers } from '@/lib/types';

/**
 * Manages crossfade transitions between scene layer sets.
 * Returns the active and transitioning layers with opacity values.
 */
export function useSceneTransition(layers: SceneLayers | null) {
  const [activeLayers, setActiveLayers] = useState<SceneLayers | null>(null);
  const [prevLayers, setPrevLayers] = useState<SceneLayers | null>(null);
  const [opacity, setOpacity] = useState(1);
  const transitionRef = useRef<number>(undefined);

  useEffect(() => {
    if (!layers) return;
    if (!activeLayers) {
      // First load — no transition
      setActiveLayers(layers);
      setOpacity(1);
      return;
    }

    // Check if scene actually changed
    if (layers.scene_id === activeLayers.scene_id) return;

    // Start crossfade
    setPrevLayers(activeLayers);
    setActiveLayers(layers);
    setOpacity(0);

    const startTime = performance.now();
    const duration = layers.weather !== activeLayers.weather ? 5000 : 3000;

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease in-out
      const eased = progress < 0.5
        ? 2 * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 2) / 2;

      setOpacity(eased);

      if (progress < 1) {
        transitionRef.current = requestAnimationFrame(animate);
      } else {
        setPrevLayers(null);
      }
    };

    transitionRef.current = requestAnimationFrame(animate);

    return () => {
      if (transitionRef.current) {
        cancelAnimationFrame(transitionRef.current);
      }
    };
  }, [layers]);

  return { activeLayers, prevLayers, opacity };
}
