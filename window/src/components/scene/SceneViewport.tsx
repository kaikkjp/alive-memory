'use client';

import { useState } from 'react';

interface SceneViewportProps {
  imageUrl: string | null;
  onLoad?: () => void;
}

/**
 * Full-bleed background scene image with crossfade on change.
 * Falls back to solid dark background when no image is available.
 */
export default function SceneViewport({ imageUrl, onLoad }: SceneViewportProps) {
  const [loaded, setLoaded] = useState(false);

  const handleLoad = () => {
    setLoaded(true);
    onLoad?.();
  };

  return (
    <div className="scene-viewport">
      {imageUrl && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={imageUrl}
          alt=""
          draggable={false}
          className="scene-viewport__image"
          style={{ opacity: loaded ? 1 : 0 }}
          onLoad={handleLoad}
        />
      )}
    </div>
  );
}
