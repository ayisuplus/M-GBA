import type { Metadata } from 'next';
import { LabWorkbench } from '@/components/LabWorkbench';

export const metadata: Metadata = {
  title: '实验工作台',
  description: '运行或回放 CAR-M 跨尺度配对实验，检查 L0–L4 传播与 L4 终点差异。',
};

export default function LabPage() {
  return <LabWorkbench />;
}
