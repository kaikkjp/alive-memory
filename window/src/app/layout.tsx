import type { Metadata } from 'next';
import './globals.css';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export const metadata: Metadata = {
  title: 'The Shopkeeper',
  description: 'A window into her world.',
  openGraph: {
    title: 'The Shopkeeper',
    description: 'A window into her world.',
    images: [`${API_BASE}/api/og`],
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'The Shopkeeper',
    description: 'A window into her world.',
    images: [`${API_BASE}/api/og`],
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
