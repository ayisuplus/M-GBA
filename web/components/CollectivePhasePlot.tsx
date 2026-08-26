'use client';

import { useMemo, useState } from 'react';
import {
  cohortName,
  collectiveStateName,
  formatMetric,
  type CollectiveComparisonCohort,
  type CollectiveConditionReport,
  type CollectiveState,
  type CollectiveTransition,
  type LabCondition,
} from '@/lib/lab';

const stateColors: Record<CollectiveState, string> = {
  low_activity: '#6f7b8e',
  activation_dominant: '#55d8a5',
  stress_dominant: '#ff6978',
  population_split: '#bf7cff',
  coactivated_balance: '#ffbd59',
  transitional: '#5ec8ff',
};

const l4Labels: Record<string, string> = {
  vitality: '活力',
  damage_burden: '损伤',
  inflammation: '炎症',
  homeostasis: '稳态',
  recovery_capacity: '恢复',
};

interface Props {
  baseline: LabCondition;
  comparison: LabCondition;
  baselineReport: CollectiveConditionReport;
  comparisonReport: CollectiveConditionReport;
  comparisonSummary?: CollectiveComparisonCohort;
  cohortId: string;
  tickIndex: number;
  onTickIndex: (index: number) => void;
}

export function CollectivePhasePlot({
  baseline,
  comparison,
  baselineReport,
  comparisonReport,
  comparisonSummary,
  cohortId,
  tickIndex,
  onTickIndex,
}: Props) {
  const [selected, setSelected] = useState<{ condition: 'baseline' | 'comparison'; transition: CollectiveTransition } | null>(null);
  const left = baselineReport.cohorts[cohortId];
  const right = comparisonReport.cohorts[cohortId];
  const width = 720;
  const height = 310;
  const plot = { left: 54, right: 18, top: 18, bottom: 42 };
  const x = (value: number) => plot.left + ((Math.max(-1, Math.min(1, value)) + 1) / 2) * (width - plot.left - plot.right);
  const y = (value: number) => plot.top + (1 - Math.max(0, Math.min(1, value))) * (height - plot.top - plot.bottom);
  const path = (series: typeof left.series) => series.map((point, index) => `${index ? 'L' : 'M'}${x(point.direction).toFixed(2)},${y(point.intensity).toFixed(2)}`).join(' ');
  const safeTick = Math.min(tickIndex, left.series.length - 1, right.series.length - 1);
  const currentLeft = left.series[safeTick];
  const currentRight = right.series[safeTick];
  const selectedCondition = selected?.condition === 'baseline' ? baseline : comparison;
  const audit = selected ? selectedCondition.ticks.find((tick) => tick.t === selected.transition.tick)?.audit : null;
  const selectedAssociation = selected?.transition.l4_association;
  const transitionCount = left.state_transitions.length + right.state_transitions.length;
  const archetypes = useMemo(() => (
    ['stable', 'single_switch', 'intermittent', 'oscillatory'] as const
  ).map((name) => ({
    name,
    baseline: left.archetype_counts[name] ?? 0,
    comparison: right.archetype_counts[name] ?? 0,
  })), [left, right]);

  function selectTransition(condition: 'baseline' | 'comparison', transition: CollectiveTransition) {
    setSelected({ condition, transition });
    const index = (condition === 'baseline' ? baseline : comparison).ticks.findIndex((tick) => tick.t === transition.tick);
    if (index >= 0) onTickIndex(index);
  }

  return (
    <div className="collective-layout">
      <div className="phase-plot-wrap">
        <svg className="phase-plot" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${cohortName(cohortId)}群体状态相图`}>
          <rect x={x(-.15)} y={y(.16)} width={x(.15) - x(-.15)} height={y(0) - y(.16)} className="phase-zone balance-zone" />
          <line x1={x(-1)} y1={y(.04)} x2={x(1)} y2={y(.04)} className="phase-threshold" />
          <line x1={x(-1)} y1={y(.16)} x2={x(1)} y2={y(.16)} className="phase-threshold" />
          <line x1={x(-.15)} y1={y(0)} x2={x(-.15)} y2={y(1)} className="phase-threshold" />
          <line x1={x(.15)} y1={y(0)} x2={x(.15)} y2={y(1)} className="phase-threshold" />
          <line x1={x(-1)} y1={y(0)} x2={x(1)} y2={y(0)} className="phase-axis" />
          <line x1={x(0)} y1={y(0)} x2={x(0)} y2={y(1)} className="phase-axis" />
          <path d={path(left.series)} className="phase-path baseline-path" />
          <path d={path(right.series)} className="phase-path comparison-path" />
          {left.series.map((point, index) => <circle key={`left-${point.t}`} cx={x(point.direction)} cy={y(point.intensity)} r={index === safeTick ? 5 : 2.1} fill={stateColors[point.state]} className={index === safeTick ? 'phase-current baseline-current' : 'phase-point'} />)}
          {right.series.map((point, index) => <circle key={`right-${point.t}`} cx={x(point.direction)} cy={y(point.intensity)} r={index === safeTick ? 6 : 2.1} fill={stateColors[point.state]} className={index === safeTick ? 'phase-current comparison-current' : 'phase-point'} />)}
          {left.state_transitions.map((transition) => {
            const point = left.series.find((item) => item.t === transition.tick);
            return point ? <circle key={`left-transition-${transition.tick}`} cx={x(point.direction)} cy={y(point.intensity)} r="9" className="transition-target baseline-transition" role="button" tabIndex={0} aria-label={`${baseline.label} tick ${transition.tick} 状态转换`} onClick={() => selectTransition('baseline', transition)} /> : null;
          })}
          {right.state_transitions.map((transition) => {
            const point = right.series.find((item) => item.t === transition.tick);
            return point ? <circle key={`right-transition-${transition.tick}`} cx={x(point.direction)} cy={y(point.intensity)} r="10" className="transition-target comparison-transition" role="button" tabIndex={0} aria-label={`${comparison.label} tick ${transition.tick} 状态转换`} onClick={() => selectTransition('comparison', transition)} /> : null;
          })}
          <text x={width / 2} y={height - 7} className="phase-label">direction · activation − stress_load</text>
          <text x="13" y={height / 2} className="phase-label vertical-label">intensity</text>
          <text x={x(-.92)} y={y(.93)} className="phase-hint">STRESS</text>
          <text x={x(.74)} y={y(.93)} className="phase-hint">ACTIVATION</text>
        </svg>
        <div className="phase-legend">
          {(Object.entries(stateColors) as Array<[CollectiveState, string]>).map(([state, color]) => <span key={state}><i style={{ background: color }} />{collectiveStateName(state)}</span>)}
        </div>
        <div className="phase-live-readout">
          <div><span>{baseline.label}</span><b>{collectiveStateName(currentLeft.state)}</b><small>m {formatMetric(currentLeft.direction)} · c {formatMetric(currentLeft.intensity)}</small></div>
          <div><span>{comparison.label}</span><b>{collectiveStateName(currentRight.state)}</b><small>m {formatMetric(currentRight.direction)} · c {formatMetric(currentRight.intensity)}</small></div>
        </div>
      </div>

      <aside className="collective-summary">
        <details open><summary>对照摘要</summary>
        <div className="trajectory-pair">
          <div><span>BASELINE 轨迹</span><b>{left.trajectory_class}</b></div>
          <div><span>干预轨迹</span><b>{right.trajectory_class}</b></div>
        </div>
        <div className="divergence-card">
          <span>首次状态分化</span>
          <b>{comparisonSummary?.first_state_divergence_tick == null ? '未观察到' : `tick ${comparisonSummary.first_state_divergence_tick}`}</b>
          <small>平均 |Δm| {formatMetric(comparisonSummary?.mean_absolute_difference.direction)}</small>
        </div>
        <div className="archetype-list"><span>个体 archetype 分布 · baseline / 干预</span>{archetypes.map((item) => <div key={item.name}><code>{item.name}</code><b>{item.baseline} / {item.comparison}</b></div>)}</div>
        {transitionCount === 0 && <div className="no-transition"><b>未观察到合格转换</b><span>冻结驻留阈值下没有持续 ≥3 tick 的状态切换。</span></div>}
        {selected && <div className="transition-detail">
          <span>{selected.condition === 'baseline' ? baseline.label : comparison.label} · tick {selected.transition.tick}</span>
          <b>{collectiveStateName(selected.transition.from_state)} → {collectiveStateName(selected.transition.to_state)}</b>
          <small>仅作时间关联，不代表因果</small>
          {selectedAssociation?.before && selectedAssociation.after && <div className="l4-transition-grid">{Object.keys(l4Labels).map((metric) => {
            const before = selectedAssociation.before!.state[metric];
            const after = selectedAssociation.after!.state[metric];
            return <div key={metric}><span>{l4Labels[metric]}</span><code>{formatMetric(before)} → {formatMetric(after)}</code><em>{after - before >= 0 ? '+' : ''}{formatMetric(after - before)}</em></div>;
          })}</div>}
          {audit && <p>事件审计：perturbation {audit.l0_perturbation_count} · transitions {audit.transition_count}</p>}
        </div>}
        {!selected && transitionCount > 0 && <p className="transition-instruction">点击相图中的空心转换点，查看 L4 前后观测与事件审计。</p>}
        </details>
      </aside>
    </div>
  );
}
