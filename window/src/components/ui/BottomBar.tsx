'use client';

/**
 * Location label (代官山) and ALIVE watermark at the bottom of the window.
 * Gradient overlay darkens the bottom for readability.
 */
export default function BottomBar() {
  return (
    <div className="bottom-bar">
      <span className="bottom-bar__location">代官山</span>
      <span className="bottom-bar__watermark">ALIVE</span>
    </div>
  );
}
