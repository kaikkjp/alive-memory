import type { Metadata } from 'next';
import ALIVEDashboard from '@/components/live/ALIVEDashboard';

export const metadata: Metadata = {
  title: 'ALIVE — The Shopkeeper',
  description: 'Real-time cognitive state of an autonomous AI character.',
  openGraph: {
    title: 'ALIVE — The Shopkeeper',
    description: 'Real-time cognitive state of an autonomous AI character.',
    type: 'website',
  },
};

export default function LivePage() {
  return <ALIVEDashboard />;
}
