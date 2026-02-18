'use client';

import ConnectionPulse from './ConnectionPulse';

interface TopBarProps {
  timeOfDay: string;
  weather: string;
  connected: boolean;
}

/**
 * Title + atmospheric status at the top of the window.
 * Gradient overlay darkens the top for text readability.
 */
export default function TopBar({ timeOfDay, weather, connected }: TopBarProps) {
  const statusParts: string[] = [];
  if (timeOfDay) statusParts.push(timeOfDay);
  if (weather) statusParts.push(weather);

  return (
    <div className="top-bar">
      <span className="top-bar__title">The Shopkeeper</span>
      <div className="top-bar__status">
        <ConnectionPulse connected={connected} />
        {statusParts.length > 0 && (
          <span>{statusParts.join(' \u00b7 ')}</span>
        )}
      </div>
    </div>
  );
}
