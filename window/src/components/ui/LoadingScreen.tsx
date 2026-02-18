'use client';

interface LoadingScreenProps {
  loaded: boolean;
}

/**
 * Dark loading screen with a breathing "…" indicator.
 * Fades out once the scene image has loaded.
 */
export default function LoadingScreen({ loaded }: LoadingScreenProps) {
  return (
    <div className={`loading-screen ${loaded ? 'loading-screen--hidden' : ''}`}>
      <span className="loading-screen__breath">&hellip;</span>
    </div>
  );
}
