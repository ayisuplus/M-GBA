import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LabWorkbench } from '@/components/LabWorkbench';
import type { CollectiveDynamicsAnalysis, LabBundle, LabCatalog, LabTick } from '@/lib/lab';

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

const collective: CollectiveDynamicsAnalysis = {
  schema_version: 'mgba-collective-dynamics-0.1',
  observer_version: 'collective-dynamics-observer-0.1',
  config_digest: 'e'.repeat(64),
  default_cohort: 'engineered_macrophage',
  scientific_boundary: 'activation-stress reference proxy；不是物理相变、真实生物机制或临床预测。',
  conditions: {
    baseline: {
      schema_version: 'mgba-collective-dynamics-0.1', observer_version: 'collective-dynamics-observer-0.1', source_experiment_id: 'exp-base', source_history_digest: 'b'.repeat(64), config_digest: 'e'.repeat(64), scientific_boundary: '不是物理相变。', report_digest: 'f'.repeat(64),
      cohorts: {
        all_cells: { cohort_id: 'all_cells', cell_ids: ['eng-mac-004', 'tumor-001'], trajectory_class: 'persistent_activation', qualified_direction_switches: 0, first_qualified_transition_tick: null, state_transitions: [], cell_archetypes: { 'eng-mac-004': 'stable', 'tumor-001': 'stable' }, archetype_counts: { stable: 2, single_switch: 0, intermittent: 0, oscillatory: 0 }, series: [
          { t: 1, direction: .1, intensity: .2, polarization: .1, edge_alignment: null, activation_dominant_fraction: .5, stress_dominant_fraction: .5, neutral_fraction: 0, state: 'population_split' },
          { t: 2, direction: .12, intensity: .2, polarization: .08, edge_alignment: null, activation_dominant_fraction: .5, stress_dominant_fraction: .5, neutral_fraction: 0, state: 'coactivated_balance' },
        ] },
        engineered_macrophage: { cohort_id: 'engineered_macrophage', cell_ids: ['eng-mac-004'], trajectory_class: 'persistent_activation', qualified_direction_switches: 0, first_qualified_transition_tick: null, state_transitions: [], cell_archetypes: { 'eng-mac-004': 'stable' }, archetype_counts: { stable: 1, single_switch: 0, intermittent: 0, oscillatory: 0 }, series: [
          { t: 1, direction: .5, intensity: .265, polarization: 0, edge_alignment: null, activation_dominant_fraction: 1, stress_dominant_fraction: 0, neutral_fraction: 0, state: 'activation_dominant' },
          { t: 2, direction: .5, intensity: .265, polarization: 0, edge_alignment: null, activation_dominant_fraction: 1, stress_dominant_fraction: 0, neutral_fraction: 0, state: 'activation_dominant' },
        ] },
      },
    },
    intervention: {
      schema_version: 'mgba-collective-dynamics-0.1', observer_version: 'collective-dynamics-observer-0.1', source_experiment_id: 'exp-int', source_history_digest: 'c'.repeat(64), config_digest: 'e'.repeat(64), scientific_boundary: '不是物理相变。', report_digest: '1'.repeat(64),
      cohorts: {
        all_cells: { cohort_id: 'all_cells', cell_ids: ['eng-mac-004', 'tumor-001'], trajectory_class: 'activation_convergence', qualified_direction_switches: 0, first_qualified_transition_tick: 2, state_transitions: [{ tick: 2, from_state: 'population_split', to_state: 'activation_dominant', source_dwell_ticks: 3, target_dwell_ticks: 3, l4_association: { relationship: 'temporal_association_only', before: { tick: 1, state: { vitality: .7, damage_burden: .3, inflammation: .2, homeostasis: .45, recovery_capacity: .6 } }, after: { tick: 2, state: { vitality: .72, damage_burden: .29, inflammation: .24, homeostasis: .6, recovery_capacity: .63 } } } }], cell_archetypes: { 'eng-mac-004': 'single_switch', 'tumor-001': 'stable' }, archetype_counts: { stable: 1, single_switch: 1, intermittent: 0, oscillatory: 0 }, series: [
          { t: 1, direction: .1, intensity: .2, polarization: .1, edge_alignment: null, activation_dominant_fraction: .5, stress_dominant_fraction: .5, neutral_fraction: 0, state: 'population_split' },
          { t: 2, direction: .25, intensity: .24, polarization: .06, edge_alignment: null, activation_dominant_fraction: .5, stress_dominant_fraction: .5, neutral_fraction: 0, state: 'activation_dominant' },
        ] },
        engineered_macrophage: { cohort_id: 'engineered_macrophage', cell_ids: ['eng-mac-004'], trajectory_class: 'persistent_activation', qualified_direction_switches: 0, first_qualified_transition_tick: 2, state_transitions: [{ tick: 2, from_state: 'coactivated_balance', to_state: 'activation_dominant', source_dwell_ticks: 3, target_dwell_ticks: 3, l4_association: { relationship: 'temporal_association_only', before: { tick: 1, state: { vitality: .7, damage_burden: .3, inflammation: .2, homeostasis: .45, recovery_capacity: .6 } }, after: { tick: 2, state: { vitality: .72, damage_burden: .29, inflammation: .24, homeostasis: .6, recovery_capacity: .63 } } } }], cell_archetypes: { 'eng-mac-004': 'stable' }, archetype_counts: { stable: 1, single_switch: 0, intermittent: 0, oscillatory: 0 }, series: [
          { t: 1, direction: .5, intensity: .265, polarization: 0, edge_alignment: null, activation_dominant_fraction: 1, stress_dominant_fraction: 0, neutral_fraction: 0, state: 'activation_dominant' },
          { t: 2, direction: .55, intensity: .3, polarization: 0, edge_alignment: null, activation_dominant_fraction: 1, stress_dominant_fraction: 0, neutral_fraction: 0, state: 'activation_dominant' },
        ] },
      },
    },
  },
  comparisons: {
    intervention: {
      schema_version: 'mgba-collective-dynamics-0.1', observer_version: 'collective-dynamics-observer-0.1', config_digest: 'e'.repeat(64), comparison_digest: '2'.repeat(64),
      cohorts: {
        all_cells: { first_state_divergence_tick: 2, mean_absolute_difference: { direction: .065, intensity: .02, polarization: .01 }, reference_trajectory_class: 'persistent_activation', comparison_trajectory_class: 'activation_convergence', trajectory_class_changed: true, l4_difference_at_divergence: null },
        engineered_macrophage: { first_state_divergence_tick: null, mean_absolute_difference: { direction: .025, intensity: .0175, polarization: 0 }, reference_trajectory_class: 'persistent_activation', comparison_trajectory_class: 'persistent_activation', trajectory_class_changed: false, l4_difference_at_divergence: null },
      },
    },
  },
};

const bundle: LabBundle = {
  schema_version: 'mgba-lab-run-bundle-0.1',
  bundle_id: 'state-intervention',
  bundle_digest: 'a'.repeat(64),
  kind: 'state_conditioned_intervention',
  title: '状态条件干预',
  description: '测试实验',
  model_status: 'reference model',
  boundary_note: '不是临床预测。',
  target_status: '真实数据 Target 已于 2026-08-28 生成（spatial-anchor-29c87ba1411d4fc8）；首次评估未锚定。ADR-0043 calibration 的 improved 输出因评估次数超出预注册上限（105 > 89），已按 ADR-0044 降级为探索性参数诊断，该 target 已消费。',
  seed: 42,
  roles: { 'eng-mac-004': 'engineered_macrophage', 'tumor-001': 'tumor' },
  layout: { 'eng-mac-004': [.3, .4], 'tumor-001': [.7, .6] },
  reference_condition: 'baseline',
  default_comparison_condition: 'intervention',
  conditions: [
    { condition_id: 'baseline', label: 'Baseline', experiment_id: 'exp-base', history_digest: 'b'.repeat(64), outcome: 'RECOVERED', terminal_l4: { vitality: .7, damage_burden: .3, inflammation: .2, homeostasis: .5, recovery_capacity: .6 }, ticks: [tick(1, .2, .45), tick(2, .2, .5)] },
    { condition_id: 'intervention', label: 'Intervention', experiment_id: 'exp-int', history_digest: 'c'.repeat(64), outcome: 'RECOVERED', terminal_l4: { vitality: .72, damage_burden: .29, inflammation: .24, homeostasis: .6, recovery_capacity: .63 }, ticks: [tick(1, .2, .45), tick(2, .7, .6)] },
  ],
  analysis: { collective_dynamics: collective }, evidence: {}, config_summary: {},
};

const catalog: LabCatalog = {
  schema_version: 'mgba-lab-catalog-0.1',
  title: 'Catalog', target_status: '真实数据 Target 已生成（2026-08-28）；首次评估未锚定；calibration improved 已按 ADR-0044 降级为探索性诊断', catalog_digest: 'd'.repeat(64),
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
  it('degrades explicitly when a replay lacks audit and L0 update markers', async () => {
    const legacyTicks = [tick(1, .2, .45), tick(2, .2, .5)].map((full) => {
      const legacy: LabTick = { ...full };
      delete legacy.l0_updated;
      delete legacy.audit;
      return legacy;
    });
    const legacyBundle: LabBundle = {
      ...bundle,
      bundle_id: 'legacy-dose',
      title: '旧回放',
      conditions: bundle.conditions.map((condition) => ({ ...condition, ticks: legacyTicks })),
    };
    render(<LabWorkbench initialBundle={legacyBundle} />);
    await screen.findByRole('heading', { name: '旧回放' });

    expect(screen.getByText('L0 更新标记在此回放缺失')).toBeInTheDocument();
    expect(screen.getByText('事件审计字段缺失')).toBeInTheDocument();
    expect(screen.getByText(/L4 OBSERVED/)).toBeInTheDocument();
    expect(screen.queryByText(/HELD/)).toBeNull();
  });

  it('labels a disabled backend fallback instead of presenting it as a live run', async () => {
    render(<LabWorkbench initialBundle={bundle} />);
    await screen.findByRole('heading', { name: '状态条件干预' });
    fireEvent.click(screen.getByRole('button', { name: /运行配对实验/ }));
    await waitFor(() => expect(screen.getByText(/明确切换到冻结预计算回放/)).toBeInTheDocument());
    expect(screen.queryByText(/在线配对运行完成/)).not.toBeInTheDocument();
  });

  it('synchronizes the phase plot, cohort switch, transition audit and boundary', async () => {
    render(<LabWorkbench initialBundle={bundle} />);
    await screen.findByRole('heading', { name: '群体状态相图' });
    expect(screen.getByRole('img', { name: '工程巨噬细胞群体状态相图' })).toBeInTheDocument();
    expect(screen.getByText('collective-dynamics-observer-0.1')).toBeInTheDocument();
    expect(screen.getByText(/不是物理相变或临床预测/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('观察 cohort'), { target: { value: 'all_cells' } });
    expect(screen.getByRole('img', { name: '全组织群体状态相图' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Intervention tick 2 状态转换' }));
    expect(screen.getByText('TICK 2 / 2')).toBeInTheDocument();
    expect(screen.getByText(/事件审计：perturbation 2/)).toBeInTheDocument();
    expect(screen.getByText('群体分化 → 激活主导')).toBeInTheDocument();
  });

  it('keeps old bundles readable when collective analysis is absent', async () => {
    render(<LabWorkbench initialBundle={{ ...bundle, analysis: {} }} />);
    await screen.findByRole('heading', { name: '状态条件干预' });
    expect(screen.getByText('该结果尚无群体动力学分析')).toBeInTheDocument();
    expect(screen.getByText(/旧分享链接仍可继续查看原始 L0–L4/)).toBeInTheDocument();
  });
});
