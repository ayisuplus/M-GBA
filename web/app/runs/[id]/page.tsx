import type { Metadata } from 'next';
import { SharedRun } from '@/components/SharedRun';

export const metadata: Metadata = {
  title: '分享实验结果',
  description: 'M-GBA 30 天可分享的跨尺度配对实验结果。',
  openGraph: { images: [] },
};

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SharedRun runId={id} />;
}
