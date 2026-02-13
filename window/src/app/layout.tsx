import type { Metadata } from 'next';
import './globals.css';

// OG images require absolute URLs for social crawlers.
// Set NEXT_PUBLIC_SITE_URL at build time in production.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:8080';

export const metadata: Metadata = {
  title: 'The Shopkeeper',
  description: 'A window into her world.',
  openGraph: {
    title: 'The Shopkeeper',
    description: 'A window into her world.',
    images: [`${SITE_URL}/api/og`],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'The Shopkeeper',
    description: 'A window into her world.',
    images: [`${SITE_URL}/api/og`],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
