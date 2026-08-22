import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'),
  title: {
    default: 'M-GBA 跨尺度虚拟实验室',
    template: '%s · M-GBA',
  },
  description: '从 L0 基因调控到 L4 宏观表型的可审计跨尺度实验工作台。',
  openGraph: {
    title: 'M-GBA 跨尺度虚拟实验室',
    description: '从 L0 基因调控到 L4 宏观表型：运行、回放并审计一次跨尺度实验。',
    type: 'website',
    locale: 'zh_CN',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'M-GBA 跨尺度虚拟实验室' }],
  },
  twitter: {
    card: 'summary_large_image',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
