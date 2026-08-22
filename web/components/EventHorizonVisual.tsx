import { createElement } from 'react';

type EventHorizonVisualProps = {
  className?: string;
  scene?: 'home' | 'trap' | 'blocked';
  depth?: number;
  intensity?: number;
  label: string;
};

export const EVENT_HORIZON_SCRIPT_SRC =
  '/__event-horizon/assets/black-hole.v1.js';

export function EventHorizonVisual({
  className,
  scene = 'home',
  depth = 0,
  intensity,
  label,
}: EventHorizonVisualProps) {
  return createElement('event-horizon-visual', {
    className,
    scene,
    depth: String(Math.max(0, depth)),
    ...(intensity == null
      ? {}
      : { intensity: String(Math.min(1, Math.max(0, intensity))) }),
    role: 'img',
    'aria-label': label,
  });
}
