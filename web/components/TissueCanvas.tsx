'use client';

import { useEffect, useRef } from 'react';
import type { FieldName, LabTick } from '@/lib/lab';

const roleColors: Record<string, string> = {
  tumor: '#ff7699',
  engineered_macrophage: '#5ce1e6',
  wild_type_macrophage: '#f5c56b',
  cd8_t_cell: '#65e6a7',
};

function fieldColor(value: number, field: FieldName, alpha: number): string {
  const v = Math.max(0, Math.min(1, value));
  if (field === 'stress') return `rgba(255,118,153,${alpha * v})`;
  if (field === 'resource_level') return `rgba(101,230,167,${alpha * v})`;
  return `rgba(92,225,230,${alpha * v})`;
}

export function TissueCanvas({
  tick,
  roles,
  layout,
  field,
  selectedCell,
  onSelect,
  label,
}: {
  tick: LabTick;
  roles: Record<string, string>;
  layout: Record<string, [number, number]>;
  field: FieldName;
  selectedCell: string;
  onSelect: (cellId: string) => void;
  label: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hitRef = useRef<Array<{ id: string; x: number; y: number; radius: number }>>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(320, rect.width);
      const height = width * 0.72;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.height = `${height}px`;
      const context = canvas.getContext('2d');
      if (!context) return;
      context.scale(ratio, ratio);
      context.fillStyle = '#061116';
      context.fillRect(0, 0, width, height);

      const background = context.createRadialGradient(width * .48, height * .45, 4, width * .48, height * .45, width * .6);
      background.addColorStop(0, '#17313a');
      background.addColorStop(1, '#071116');
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);

      if (tick.field) {
        const channel = field === 'stress' ? 2 : field === 'resource_level' ? 3 : 4;
        const cellWidth = width / tick.field.columns;
        const cellHeight = height / tick.field.rows;
        for (const cell of tick.field.cells) {
          context.fillStyle = fieldColor(cell[channel], field, .72);
          context.fillRect(cell[1] * cellWidth, cell[0] * cellHeight, cellWidth + .5, cellHeight + .5);
        }
      } else {
        for (const [cellId, state] of Object.entries(tick.cells)) {
          const [nx, ny] = tick.coordinates?.[cellId] ?? layout[cellId] ?? [.5, .5];
          const value = state.node[field];
          const glow = context.createRadialGradient(nx * width, ny * height, 0, nx * width, ny * height, 28 + 30 * value);
          glow.addColorStop(0, fieldColor(value, field, .38));
          glow.addColorStop(1, fieldColor(value, field, 0));
          context.fillStyle = glow;
          context.fillRect(nx * width - 70, ny * height - 70, 140, 140);
        }
      }

      const positions = tick.coordinates ?? layout;
      context.lineWidth = .6;
      context.strokeStyle = 'rgba(118,170,184,.16)';
      for (const [source, target] of (tick.edges ?? []).slice(0, 420)) {
        const left = positions[source];
        const right = positions[target];
        if (!left || !right) continue;
        context.beginPath();
        context.moveTo(left[0] * width, left[1] * height);
        context.lineTo(right[0] * width, right[1] * height);
        context.stroke();
      }

      const hit: Array<{ id: string; x: number; y: number; radius: number }> = [];
      for (const cellId of Object.keys(tick.cells).sort()) {
        const position = positions[cellId] ?? layout[cellId];
        if (!position) continue;
        const x = position[0] * width;
        const y = position[1] * height;
        const radius = cellId === selectedCell ? 5.4 : 3.5;
        const color = roleColors[roles[cellId]] ?? '#b8ccd2';
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fillStyle = color;
        context.shadowColor = color;
        context.shadowBlur = cellId === selectedCell ? 16 : 7;
        context.fill();
        context.shadowBlur = 0;
        if (cellId === selectedCell) {
          context.beginPath();
          context.arc(x, y, 9, 0, Math.PI * 2);
          context.strokeStyle = '#ffffff';
          context.lineWidth = 1.4;
          context.stroke();
        }
        hit.push({ id: cellId, x, y, radius: 12 });
      }
      hitRef.current = hit;
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [field, layout, roles, selectedCell, tick]);

  return (
    <canvas
      ref={canvasRef}
      className="tissue-canvas"
      aria-label={label}
      role="img"
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        const nearest = hitRef.current
          .map((item) => ({ ...item, distance: Math.hypot(item.x - x, item.y - y) }))
          .filter((item) => item.distance <= item.radius)
          .sort((a, b) => a.distance - b.distance)[0];
        if (nearest) onSelect(nearest.id);
      }}
    />
  );
}
