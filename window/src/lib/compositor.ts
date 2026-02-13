/** Canvas drawing utilities for scene composition. */

const imageCache = new Map<string, HTMLImageElement>();
const MAX_CACHE_SIZE = 200;

const ASSET_BASE = process.env.NEXT_PUBLIC_ASSET_URL || '/assets';

/** Sanitize a filename to prevent path traversal. */
function sanitizeFilename(name: string): string {
  return name.replace(/\.\./g, '').replace(/[/\\]/g, '').replace(/[^a-zA-Z0-9_\-.]/g, '');
}

export function getAssetUrl(category: string, filename: string): string {
  const safeCategory = sanitizeFilename(category);
  const safeFilename = sanitizeFilename(filename);
  return `${ASSET_BASE}/${safeCategory}/${safeFilename}`;
}

export async function loadImage(src: string): Promise<HTMLImageElement> {
  const cached = imageCache.get(src);
  if (cached?.complete) return cached;

  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      // Evict oldest entries when cache exceeds limit
      if (imageCache.size >= MAX_CACHE_SIZE) {
        const firstKey = imageCache.keys().next().value;
        if (firstKey !== undefined) imageCache.delete(firstKey);
      }
      imageCache.set(src, img);
      resolve(img);
    };
    img.onerror = () => {
      // Don't reject — return a transparent placeholder
      console.warn(`[compositor] Failed to load: ${src}`);
      resolve(img); // img will be 0x0, drawing it is a no-op
    };
    img.src = src;
  });
}

export async function drawImage(
  ctx: CanvasRenderingContext2D,
  src: string,
): Promise<void> {
  const img = await loadImage(src);
  if (img.width > 0 && img.height > 0) {
    ctx.drawImage(img, 0, 0, ctx.canvas.width, ctx.canvas.height);
  }
}

export async function drawImageAt(
  ctx: CanvasRenderingContext2D,
  src: string,
  x: number,
  y: number,
  width: number,
  height: number,
): Promise<void> {
  const img = await loadImage(src);
  if (img.width > 0 && img.height > 0) {
    ctx.drawImage(img, x, y, width, height);
  }
}

/** Preload an array of image URLs. */
export async function preloadImages(urls: string[]): Promise<void> {
  await Promise.allSettled(urls.map(loadImage));
}
