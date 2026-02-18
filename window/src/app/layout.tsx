import type { Metadata, Viewport } from 'next';
import './globals.css';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:8080';

export const metadata: Metadata = {
  title: 'The Shopkeeper',
  description: 'A quiet shop in Tokyo. Someone is inside.',
  openGraph: {
    title: 'The Shopkeeper',
    description: 'A quiet shop in Tokyo. Someone is inside.',
    images: [`${SITE_URL}/api/og`],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'The Shopkeeper',
    description: 'A quiet shop in Tokyo. Someone is inside.',
    images: [`${SITE_URL}/api/og`],
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  viewportFit: 'cover',
  themeColor: '#0d0b09',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;1,400&family=DM+Sans:wght@400;500&family=Noto+Serif+JP:wght@300;400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
