'use client';

import { useEffect, useRef } from 'react';
import type { LabCondition } from '@/lib/lab';
import { l4Series } from '@/lib/lab';

export function MetricChart({ baseline, comparison, metric, label }: {
  baseline: LabCondition;
  comparison: LabCondition;
  metric: string;
  label: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const width = 260;
    const height = 82;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    const series = [l4Series(baseline, metric), l4Series(comparison, metric)];
    const values = series.flatMap((item) => item.map(([, value]) => value));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, .03);
    context.strokeStyle = '#1b303b';
    context.lineWidth = 1;
    for (let y = 18; y < height; y += 20) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
    }
    series.forEach((points, index) => {
      context.beginPath();
      points.forEach(([tick, value], pointIndex) => {
        const x = ((tick - 1) / Math.max(1, baseline.ticks.length - 1)) * (width - 8) + 4;
        const y = height - 8 - ((value - min) / range) * (height - 18);
        if (pointIndex === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.strokeStyle = index === 0 ? '#78909b' : '#5ce1e6';
      context.lineWidth = index === 0 ? 1.2 : 2;
      context.stroke();
    });
  }, [baseline, comparison, metric]);
  return <figure className="metric-chart"><figcaption>{label}</figcaption><canvas ref={ref} aria-label={`${label} 时间序列`} /></figure>;
}
