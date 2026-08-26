export const LAB_REQUEST_SCHEMA = 'mgba-lab-experiment-request-0.1';
export const LAB_EXECUTION_REVISION = 'carm-state-conditioned-paired-0.3';

export type FieldName = 'stress' | 'signal' | 'resource_level';

export interface LabCatalogEntry {
  bundle_id: string;
  kind: string;
  title: string;
  description: string;
  path: string;
  ticks: number;
  cell_count: number;
  condition_count: number;
  default_comparison_condition: string;
  bundle_digest: string;
}

export interface LabCatalog {
  schema_version: string;
  title: string;
  target_status: string;
  catalog_digest: string;
  experiments: LabCatalogEntry[];
}

export interface CellDisplayState {
  phase: string;
  viability: number;
  activation: number;
  stress_load: number;
  collective_response?: number;
  l0: Record<string, number>;
  l1: Record<string, number>;
  node: { stress: number; signal: number; resource_level: number };
}

export interface LabTick {
  t: number;
  // playbook-era bundles predate these display fields; absent means unknown, never HELD/zero.
  l0_updated?: boolean;
  l4_observed: boolean;
  audit?: {
    transition_count: number;
    l0_perturbation_count: number;
    layer_paths: string[];
  };
  cells: Record<string, CellDisplayState>;
  l3: Record<string, number>;
  l4: Record<string, number> | null;
  edges?: [string, string][];
  coordinates?: Record<string, [number, number]>;
  field?: {
    rows: number;
    columns: number;
    cells: [number, number, number, number, number][];
  };
}

export interface LabCondition {
  condition_id: string;
  label: string;
  experiment_id: string;
  history_digest: string;
  outcome: string;
  terminal_l4: Record<string, number>;
  ticks: LabTick[];
}

export interface LabBundle {
  schema_version: string;
  bundle_id: string;
  bundle_digest: string;
  kind: string;
  title: string;
  description: string;
  model_status: string;
  boundary_note: string;
  target_status: string;
  seed: number;
  roles: Record<string, string>;
  layout: Record<string, [number, number]>;
  reference_condition: string;
  default_comparison_condition: string;
  conditions: LabCondition[];
  analysis: Record<string, unknown>;
  evidence: Record<string, unknown>;
  config_summary: Record<string, unknown>;
}

export type CollectiveState =
  | 'low_activity'
  | 'activation_dominant'
  | 'stress_dominant'
  | 'population_split'
  | 'coactivated_balance'
  | 'transitional';

export interface CollectivePoint {
  t: number;
  direction: number;
  intensity: number;
  polarization: number;
  edge_alignment: number | null;
  activation_dominant_fraction: number;
  stress_dominant_fraction: number;
  neutral_fraction: number;
  state: CollectiveState;
}

export interface CollectiveL4State {
  tick: number;
  state: Record<string, number>;
}

export interface CollectiveTransition {
  tick: number;
  from_state: CollectiveState;
  to_state: CollectiveState;
  source_dwell_ticks: number;
  target_dwell_ticks: number;
  l4_association: {
    relationship: 'temporal_association_only';
    before: CollectiveL4State | null;
    after: CollectiveL4State | null;
  };
}

export interface CollectiveCohortReport {
  cohort_id: string;
  cell_ids: string[];
  series: CollectivePoint[];
  trajectory_class: string;
  qualified_direction_switches: number;
  first_qualified_transition_tick: number | null;
  state_transitions: CollectiveTransition[];
  cell_archetypes: Record<string, 'stable' | 'single_switch' | 'intermittent' | 'oscillatory'>;
  archetype_counts: Record<'stable' | 'single_switch' | 'intermittent' | 'oscillatory', number>;
}

export interface CollectiveConditionReport {
  schema_version: 'mgba-collective-dynamics-0.1';
  observer_version: string;
  source_experiment_id: string;
  source_history_digest: string;
  config_digest: string;
  scientific_boundary: string;
  cohorts: Record<string, CollectiveCohortReport>;
  report_digest: string;
}

export interface CollectiveComparisonCohort {
  first_state_divergence_tick: number | null;
  mean_absolute_difference: {
    direction: number;
    intensity: number;
    polarization: number;
  };
  reference_trajectory_class: string;
  comparison_trajectory_class: string;
  trajectory_class_changed: boolean;
  l4_difference_at_divergence: {
    relationship: 'temporal_association_only';
    reference_tick: number;
    comparison_tick: number;
    delta: Record<string, number>;
  } | null;
}

export interface CollectiveComparison {
  schema_version: 'mgba-collective-dynamics-0.1';
  observer_version: string;
  config_digest: string;
  cohorts: Record<string, CollectiveComparisonCohort>;
  comparison_digest: string;
}

export interface CollectiveDynamicsAnalysis {
  schema_version: 'mgba-collective-dynamics-0.1';
  observer_version: string;
  config_digest: string;
  default_cohort: string;
  scientific_boundary: string;
  conditions: Record<string, CollectiveConditionReport>;
  comparisons: Record<string, CollectiveComparison>;
}

export interface LabExperimentRequest {
  schema_version: typeof LAB_REQUEST_SCHEMA;
  scenario_id: 'carm_high_immune_her2';
  protocol_id: 'state_conditioned_signal_expression';
  dose: 0 | 0.7 | 1;
  onset: 'early' | 'late';
  exposure: 'short' | 'long';
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

export function findCondition(bundle: LabBundle, id: string): LabCondition {
  const condition = bundle.conditions.find((item) => item.condition_id === id);
  if (!condition) throw new Error(`Unknown condition: ${id}`);
  return condition;
}

export function l4Series(condition: LabCondition, metric: string): Array<[number, number]> {
  const observed = condition.ticks
    .filter((tick) => tick.l4 && typeof tick.l4[metric] === 'number')
    .map((tick) => [tick.t, tick.l4![metric]] as [number, number]);
  // terminal_l4 belongs to the final tick, which may not be an L4-observed tick;
  // anchor it to that tick's own t rather than assuming 1-based contiguous time.
  const finalTick = condition.ticks[condition.ticks.length - 1];
  if (observed.length && finalTick && !observed.some(([tick]) => tick === finalTick.t)) {
    observed.push([finalTick.t, condition.terminal_l4[metric]]);
  }
  return observed;
}

export function formatMetric(value: number | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

export function roleName(role: string): string {
  return ({
    tumor: '肿瘤细胞',
    engineered_macrophage: '工程巨噬细胞',
    wild_type_macrophage: '野生型巨噬细胞',
    cd8_t_cell: 'CD8 T 细胞',
  } as Record<string, string>)[role] ?? role;
}

export function collectiveDynamics(bundle: LabBundle): CollectiveDynamicsAnalysis | null {
  const value = bundle.analysis.collective_dynamics;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const candidate = value as Partial<CollectiveDynamicsAnalysis>;
  if (
    candidate.schema_version !== 'mgba-collective-dynamics-0.1'
    || typeof candidate.observer_version !== 'string'
    || typeof candidate.config_digest !== 'string'
    || typeof candidate.default_cohort !== 'string'
    || !candidate.conditions
    || !candidate.comparisons
  ) return null;
  return candidate as CollectiveDynamicsAnalysis;
}

export function collectiveStateName(state: CollectiveState): string {
  return ({
    low_activity: '低活动',
    activation_dominant: '激活主导',
    stress_dominant: '压力主导',
    population_split: '群体分化',
    coactivated_balance: '共激活平衡',
    transitional: '过渡态',
  } as Record<CollectiveState, string>)[state];
}

export function cohortName(cohort: string): string {
  return cohort === 'all_cells' ? '全组织' : roleName(cohort);
}
