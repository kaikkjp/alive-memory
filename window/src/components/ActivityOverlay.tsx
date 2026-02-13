'use client';

interface ActivityOverlayProps {
  label: string;
}

/**
 * Semi-transparent label overlaid on the canvas showing current activity.
 * e.g. "Reading", "Writing in her journal", "Arranging the shelf"
 */
export default function ActivityOverlay({ label }: ActivityOverlayProps) {
  if (!label) return null;

  return (
    <div className="activity-overlay">
      <span className="activity-overlay__label">{label}</span>
    </div>
  );
}
