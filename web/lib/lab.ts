export const LAB_REQUEST_SCHEMA = 'mgba-lab-experiment-request-0.1';
export const LAB_EXECUTION_REVISION = 'carm-state-conditioned-paired-0.1';

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
  l0: Record<string, number>;
  l1: Record<string, number>;
  node: { stress: number; signal: number; resource_level: number };
}

export interface LabTick {
  t: number;
  l0_updated: boolean;
  l4_observed: boolean;
  audit: {
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
  if (observed.length && !observed.some(([tick]) => tick === condition.ticks.length)) {
    observed.push([condition.ticks.length, condition.terminal_l4[metric]]);
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
