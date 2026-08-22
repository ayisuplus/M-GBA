import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Home from '@/app/page';
import { GET, HEAD } from '@/app/api/event-horizon/assets/[asset]/route';
import {
  EVENT_HORIZON_SCRIPT_SRC,
  EventHorizonVisual,
} from '@/components/EventHorizonVisual';

const assetPath = resolve(
  process.cwd(),
  'lib/black-hole.v1.js',
);

describe('event horizon visual', () => {
  it('does not load or render the optional visual on the normal landing page', () => {
    const { container } = render(<Home />);

    expect(container.querySelector('event-horizon-visual')).toBeNull();
    expect(
      container.querySelector(`script[src="${EVENT_HORIZON_SCRIPT_SRC}"]`),
    ).toBeNull();
    expect(container.querySelector('.hero-flow')).not.toBeNull();
  });

  it('renders the public Web Component contract without reading experiment state', () => {
    const { container } = render(
      <EventHorizonVisual
        className="test-visual"
        scene="home"
        depth={2}
        intensity={0.68}
        label="只读视觉"
      />,
    );

    const visual = container.querySelector('event-horizon-visual');
    expect(visual).toHaveAttribute('class', 'test-visual');
    expect(visual).toHaveAttribute('scene', 'home');
    expect(visual).toHaveAttribute('depth', '2');
    expect(visual).toHaveAttribute('intensity', '0.68');
    expect(visual).toHaveAttribute('role', 'img');
    expect(visual).toHaveAttribute('aria-label', '只读视觉');
    expect(EVENT_HORIZON_SCRIPT_SRC).toBe(
      '/__event-horizon/assets/black-hole.v1.js',
    );
  });

  it('keeps the versioned renderer self-contained and disposable', () => {
    const source = readFileSync(assetPath, 'utf8');

    expect(source).toContain('customElements.define("event-horizon-visual"');
    expect(source).toContain('this.dataset.blackHoleReady = "true"');
    expect(source).toContain('resizeObserver?.disconnect()');
    expect(source).toContain('prefers-reduced-motion: reduce');
    expect(source).not.toMatch(/https?:\/\//);
    expect(source).not.toMatch(/\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(/);
  });

  it('serves one immutable same-origin JavaScript response contract', async () => {
    const request = new Request(
      'https://example.test/api/event-horizon/assets/black-hole.v1.js',
    );
    const context = {
      params: Promise.resolve({ asset: 'black-hole.v1.js' }),
    };
    const response = await GET(request, context);
    const headResponse = await HEAD(request, context);

    expect(response.headers.get('content-type')).toBe(
      'application/javascript; charset=utf-8',
    );
    expect(response.headers.get('cache-control')).toBe(
      'public, max-age=31536000, immutable',
    );
    expect(response.headers.get('cross-origin-resource-policy')).toBe(
      'same-origin',
    );
    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
    expect(await response.text()).toContain(
      'customElements.define("event-horizon-visual"',
    );
    expect(await headResponse.text()).toBe('');
  });
});
