import type { NextConfig } from 'next';

/**
 * Static export is used for production (served by nginx).
 * During `next dev`, rewrites proxy /assets/* to the heartbeat_server
 * so sprites and scene images load without running prepare_assets.sh.
 *
 * Build for production:  BUILD_EXPORT=1 next build
 * Dev server:            next dev  (rewrites active, no static export)
 */
const isStaticExport = process.env.BUILD_EXPORT === '1';

const nextConfig: NextConfig = {
  ...(isStaticExport ? { output: 'export' as const } : {}),
  images: {
    unoptimized: true,
  },
  ...(!isStaticExport
    ? {
        async rewrites() {
          const backendUrl =
            process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
          return [
            {
              source: '/assets/:path*',
              destination: `${backendUrl}/assets/:path*`,
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
