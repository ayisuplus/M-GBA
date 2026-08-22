import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SharedRun } from '@/components/SharedRun';

describe('shared run states', () => {
  it.each([
    [404, '没有找到这个实验'],
    [410, '这个分享结果已经过期'],
  ])('renders HTTP %s explicitly', async (status, message) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'test' }), { status })));
    render(<SharedRun runId="lab-run-0123456789abcdef" />);
    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});
