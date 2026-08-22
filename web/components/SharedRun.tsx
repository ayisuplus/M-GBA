'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LabWorkbench } from '@/components/LabWorkbench';
import { SiteHeader } from '@/components/SiteHeader';
import type { LabBundle } from '@/lib/lab';

export function SharedRun({ runId }: { runId: string }) {
  const [bundle, setBundle] = useState<LabBundle | null>(null);
  const [status, setStatus] = useState<'loading' | 'missing' | 'expired' | 'error'>('loading');

  useEffect(() => {
    fetch(`/api/experiments/${encodeURIComponent(runId)}`, { headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (response.status === 404) { setStatus('missing'); return; }
        if (response.status === 410) { setStatus('expired'); return; }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json() as { bundle: LabBundle };
        setBundle(payload.bundle);
      })
      .catch(() => setStatus('error'));
  }, [runId]);

  if (bundle) return <LabWorkbench initialBundle={bundle} />;
  const messages = {
    loading: ['正在读取分享结果', '正在校验 30 天 R2 缓存与 bundle digest。'],
    missing: ['没有找到这个实验', 'run ID 不存在，或结果尚未成功保存。'],
    expired: ['这个分享结果已经过期', '公共结果只保留 30 天；你仍可打开冻结预计算实验。'],
    error: ['暂时无法读取结果', '请稍后重试，或使用完全离线的比赛回放。'],
  } as const;
  return <main className="preview-shell"><SiteHeader active="lab" /><div className="loading-state"><i /><b>{messages[status][0]}</b><span>{messages[status][1]}</span><Link className="secondary-cta" href="/lab">返回实验工作台</Link></div></main>;
}
