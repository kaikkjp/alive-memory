'use client';

/**
 * CSS glass reflection + vignette overlay.
 * Simulates peering through a shop window at night.
 */
export default function GlassOverlay() {
  return (
    <div className="glass-overlay">
      <div className="glass-overlay__vignette" />
      <div className="glass-overlay__reflection" />
    </div>
  );
}
