import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LabWorkbench } from '@/components/LabWorkbench';
import type { LabBundle, LabCatalog, LabTick } from '@/lib/lab';

vi.mock('@/components/TissueCanvas', () => ({
  TissueCanvas: ({ field, label, onSelect }: { field: string; label: string; onSelect: (id: string) => void }) => <button aria-label={label} data-field={field} onClick={() => onSelect('tumor-001')}>canvas:{field}</button>,
}));
vi.mock('@/components/MetricChart', () => ({
  MetricChart: ({ label }: { label: string }) => <div data-testid="metric-chart">{label}</div>,
}));

function tick(t: number, signal: number, homeostasis: number): LabTick {
  return {
    t,
    l0_updated: t === 1,
    l4_observed: true,
    audit: { transition_count: 8, l0_perturbation_count: t === 2 ? 2 : 0, layer_paths: ['L0→L1'] },
    cells: {
      'eng-mac-004': { phase: 'activated', viability: 1, activation: .7, stress_load: .2, l0: { signal_expression: signal }, l1: { signal_protein: signal * .8 }, node: { stress: .2, signal, resource_level: .8 } },
      'tumor-001': { phase: 'stressed', viability: .8, activation: .1, stress_load: .6, l0: { signal_expression: .1 }, l1: { signal_protein: .08 }, node: { stress: .6, signal: .1, resource_level: .4 } },
    },
    l3: { mean_stress: .4 },
    l4: { homeostasis },
  };
}

const bundle: LabBundle = {
  schema_version: 'mgba-lab-run-bundle-0.1',
  bundle_id: 'state-intervention',
  bundle_digest: 'a'.repeat(64),
  kind: 'state_conditioned_intervention',
  title: '状态条件干预',
  description: '测试实验',
  model_status: 'reference model',
  boundary_note: '不是临床预测。',
  target_status: '真实数据 Target 尚未生成',
  seed: 42,
  roles: { 'eng-mac-004': 'engineered_macrophage', 'tumor-001': 'tumor' },
  layout: { 'eng-mac-004': [.3, .4], 'tumor-001': [.7, .6] },
  reference_condition: 'baseline',
  default_comparison_condition: 'intervention',
  conditions: [
    { condition_id: 'baseline', label: 'Baseline', experiment_id: 'exp-base', history_digest: 'b'.repeat(64), outcome: 'RECOVERED', terminal_l4: { vitality: .7, damage_burden: .3, inflammation: .2, homeostasis: .5, recovery_capacity: .6 }, ticks: [tick(1, .2, .45), tick(2, .2, .5)] },
    { condition_id: 'intervention', label: 'Intervention', experiment_id: 'exp-int', history_digest: 'c'.repeat(64), outcome: 'RECOVERED', terminal_l4: { vitality: .72, damage_burden: .29, inflammation: .24, homeostasis: .6, recovery_capacity: .63 }, ticks: [tick(1, .2, .45), tick(2, .7, .6)] },
  ],
  analysis: {}, evidence: {}, config_summary: {},
};

const catalog: LabCatalog = {
  schema_version: 'mgba-lab-catalog-0.1',
  title: 'Catalog', target_status: '真实数据 Target 尚未生成', catalog_digest: 'd'.repeat(64),
  experiments: [{ bundle_id: 'state-intervention', kind: bundle.kind, title: bundle.title, description: bundle.description, path: '/lab-data/state-intervention.json', ticks: 2, cell_count: 2, condition_count: 2, default_comparison_condition: 'intervention', bundle_digest: bundle.bundle_digest }],
};

describe('lab workbench', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const path = String(input);
      if (path.includes('catalog.json')) return new Response(JSON.stringify(catalog), { status: 200 });
      if (path.includes('state-intervention.json')) return new Response(JSON.stringify(bundle), { status: 200 });
      return new Response(JSON.stringify({ error: 'live_runner_disabled' }), { status: 503 });
    }));
  });

  it('keeps tick, selected cell, field and L4 differences synchronized', async () => {
    render(<LabWorkbench initialBundle={bundle} />);
    await screen.findByRole('heading', { name: '状态条件干预' });
    expect(screen.getAllByTestId('metric-chart')).toHaveLength(5);
    expect(screen.getByText('+0.100')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('实验 tick'), { target: { value: '1' } });
    expect(screen.getByText('TICK 2 / 2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '压力' }));
    expect(screen.getAllByText('canvas:stress')).toHaveLength(2);

    fireEvent.click(screen.getAllByRole('button', { name: /Baseline 组织状态/ })[0]);
    expect(screen.getByText(/tumor-001/)).toBeInTheDocument();
  });

  it('labels a disabled backend fallback instead of presenting it as a live run', async () => {
    render(<LabWorkbench initialBundle={bundle} />);
    await screen.findByRole('heading', { name: '状态条件干预' });
    fireEvent.click(screen.getByRole('button', { name: /运行配对实验/ }));
    await waitFor(() => expect(screen.getByText(/明确切换到冻结预计算回放/)).toBeInTheDocument());
    expect(screen.queryByText(/在线配对运行完成/)).not.toBeInTheDocument();
  });
});
