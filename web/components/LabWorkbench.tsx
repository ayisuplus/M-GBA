'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { MetricChart } from '@/components/MetricChart';
import { SiteHeader } from '@/components/SiteHeader';
import { TissueCanvas } from '@/components/TissueCanvas';
import {
  LAB_REQUEST_SCHEMA,
  fetchJson,
  findCondition,
  formatMetric,
  roleName,
  type FieldName,
  type LabBundle,
  type LabCatalog,
  type LabCatalogEntry,
  type LabExperimentRequest,
} from '@/lib/lab';

const l4Metrics = [
  ['vitality', '活力'],
  ['damage_burden', '损伤负担'],
  ['inflammation', '炎症'],
  ['homeostasis', '稳态'],
  ['recovery_capacity', '恢复能力'],
] as const;

function delta(left: number | undefined, right: number | undefined): string {
  if (typeof left !== 'number' || typeof right !== 'number') return '—';
  const value = right - left;
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`;
}

export function LabWorkbench({ initialBundle }: { initialBundle?: LabBundle }) {
  const initialCell = initialBundle
    ? Object.keys(initialBundle.roles).find((id) => initialBundle.roles[id] === 'engineered_macrophage') ?? Object.keys(initialBundle.roles)[0]
    : 'eng-mac-004';
  const [catalog, setCatalog] = useState<LabCatalog | null>(null);
  const [bundle, setBundle] = useState<LabBundle | null>(initialBundle ?? null);
  const [selectedBundleId, setSelectedBundleId] = useState(initialBundle?.bundle_id ?? 'state-intervention');
  const [comparisonId, setComparisonId] = useState(initialBundle?.default_comparison_condition ?? '');
  const [tickIndex, setTickIndex] = useState(0);
  const [selectedCell, setSelectedCell] = useState(initialCell);
  const [field, setField] = useState<FieldName>('signal');
  const [playing, setPlaying] = useState(false);
  const [dose, setDose] = useState<0 | 0.7 | 1>(0.7);
  const [onset, setOnset] = useState<'early' | 'late'>('late');
  const [exposure, setExposure] = useState<'short' | 'long'>('long');
  const [runState, setRunState] = useState<'idle' | 'running' | 'online' | 'fallback' | 'error'>('idle');
  const [runMessage, setRunMessage] = useState('三套冻结实验可离线回放；在线服务未启用时自动回退。');
  const [liveRunId, setLiveRunId] = useState<string | null>(null);

  useEffect(() => {
    fetchJson<LabCatalog>('/lab-data/catalog.json')
      .then((next) => {
        setCatalog(next);
        if (!initialBundle) {
          const preferred = next.experiments.find((item) => item.bundle_id === 'state-intervention') ?? next.experiments[0];
          return fetchJson<LabBundle>(preferred.path);
        }
        return null;
      })
      .then((next) => {
        if (next) {
          setBundle(next);
          setComparisonId(next.default_comparison_condition);
          setTickIndex(0);
          const preferred = Object.keys(next.roles).find((id) => next.roles[id] === 'engineered_macrophage');
          setSelectedCell(preferred ?? Object.keys(next.roles)[0]);
        }
      })
      .catch(() => setRunState('error'));
  }, [initialBundle]);

  useEffect(() => {
    if (!playing || !bundle) return;
    const maximum = Math.min(...bundle.conditions.map((condition) => condition.ticks.length)) - 1;
    const timer = window.setInterval(() => {
      setTickIndex((current) => current >= maximum ? 0 : current + 1);
    }, 420);
    return () => window.clearInterval(timer);
  }, [bundle, playing]);

  const baseline = useMemo(() => bundle ? findCondition(bundle, bundle.reference_condition) : null, [bundle]);
  const comparison = useMemo(() => {
    if (!bundle) return null;
    return findCondition(bundle, comparisonId || bundle.default_comparison_condition);
  }, [bundle, comparisonId]);

  if (!catalog || !bundle || !baseline || !comparison) {
    return (
      <main className="preview-shell"><SiteHeader active="lab" /><div className="loading-state"><i /><b>正在校验实验 catalog</b><span>只加载小型索引，轨迹将按需读取。</span></div></main>
    );
  }

  const maximumTick = Math.min(baseline.ticks.length, comparison.ticks.length) - 1;
  const safeTick = Math.min(tickIndex, maximumTick);
  const baseTick = baseline.ticks[safeTick];
  const compareTick = comparison.ticks[safeTick];
  const baseCell = baseTick.cells[selectedCell];
  const compareCell = compareTick.cells[selectedCell];
  const catalogEntry = catalog.experiments.find((item) => item.bundle_id === selectedBundleId);

  async function loadExperiment(entry: LabCatalogEntry) {
    setPlaying(false);
    setSelectedBundleId(entry.bundle_id);
    setRunState('idle');
    setLiveRunId(null);
    const next = await fetchJson<LabBundle>(entry.path);
    setBundle(next);
    setComparisonId(next.default_comparison_condition);
    setTickIndex(0);
    const preferred = Object.keys(next.roles).find((id) => next.roles[id] === 'engineered_macrophage');
    setSelectedCell(preferred ?? Object.keys(next.roles)[0]);
  }

  async function runLivePair() {
    setPlaying(false);
    setRunState('running');
    setRunMessage('正在执行 baseline 与 intervention 配对；不会运行完整 15-run 矩阵。');
    const request: LabExperimentRequest = {
      schema_version: LAB_REQUEST_SCHEMA,
      scenario_id: 'carm_high_immune_her2',
      protocol_id: 'state_conditioned_signal_expression',
      dose,
      onset,
      exposure,
    };
    try {
      const response = await fetch('/api/experiments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(request),
      });
      const payload = await response.json() as { run_id?: string; bundle?: LabBundle; error?: string };
      if (!response.ok || !payload.bundle || !payload.run_id) throw new Error(payload.error ?? `HTTP ${response.status}`);
      setBundle(payload.bundle);
      setSelectedBundleId(payload.bundle.bundle_id);
      setComparisonId(payload.bundle.default_comparison_condition);
      setTickIndex(0);
      const preferred = Object.keys(payload.bundle.roles).find((id) => payload.bundle!.roles[id] === 'engineered_macrophage');
      setSelectedCell(preferred ?? Object.keys(payload.bundle.roles)[0]);
      setLiveRunId(payload.run_id);
      setRunState('online');
      setRunMessage('在线配对运行完成；结果已保存 30 天，并保留实验与 history digest。');
    } catch {
      const fallback = catalog.experiments.find((item) => item.bundle_id === 'state-intervention');
      if (fallback) {
        const fallbackBundle = await fetchJson<LabBundle>(fallback.path);
        setBundle(fallbackBundle);
        setSelectedBundleId(fallback.bundle_id);
        setComparisonId(fallbackBundle.default_comparison_condition);
        setTickIndex(0);
        const preferred = Object.keys(fallbackBundle.roles).find((id) => fallbackBundle.roles[id] === 'engineered_macrophage');
        setSelectedCell(preferred ?? Object.keys(fallbackBundle.roles)[0]);
        setRunState('fallback');
        setRunMessage('在线后端当前不可用，现已明确切换到冻结预计算回放；这不是本次在线计算结果。');
      } else {
        setRunState('error');
        setRunMessage('在线后端和预计算回放均不可用。');
      }
    }
  }

  return (
    <main className="preview-shell">
      <SiteHeader active="lab" />
      <section className="stage-heading">
        <div><p className="eyebrow">{bundle.kind.replaceAll('_', ' ')} · SEED {bundle.seed}</p><h1>{bundle.title}</h1><p className="stage-description">{bundle.description}</p></div>
        <div className="stage-meta"><span>{baseline.ticks.length} TICKS</span><span>{Object.keys(bundle.roles).length} CELLS</span><span>{bundle.conditions.length} CONDITIONS</span></div>
      </section>

      <section className="lab-grid">
        <aside className="panel controls-panel">
          <div className="panel-title"><span>01</span><div><b>实验设置</b><small>冻结协议 · 严格枚举</small></div></div>
          <label>预计算实验库
            <select value={selectedBundleId.startsWith('lab-run-') ? 'state-intervention' : selectedBundleId} onChange={(event) => {
              const entry = catalog.experiments.find((item) => item.bundle_id === event.target.value);
              if (entry) void loadExperiment(entry);
            }}>
              {catalog.experiments.map((entry) => <option value={entry.bundle_id} key={entry.bundle_id}>{entry.title}</option>)}
            </select>
          </label>
          <label>当前对照条件
            <select value={comparison.condition_id} onChange={(event) => { setComparisonId(event.target.value); setTickIndex(0); }}>
              {bundle.conditions.filter((item) => item.condition_id !== bundle.reference_condition).map((item) => <option key={item.condition_id} value={item.condition_id}>{item.label}</option>)}
            </select>
          </label>
          <div className="control-group"><span>在线 CAR 信号剂量</span><div className="segment">{([0, .7, 1] as const).map((value) => <button key={value} className={dose === value ? 'selected' : ''} onClick={() => setDose(value)}>{value.toFixed(1)}</button>)}</div></div>
          <div className="control-group"><span>干预时机</span><div className="segment">{(['early', 'late'] as const).map((value) => <button key={value} className={onset === value ? 'selected' : ''} onClick={() => setOnset(value)}>{value === 'early' ? 'Early' : 'Late'}</button>)}</div></div>
          <div className="control-group"><span>暴露长度</span><div className="segment">{(['short', 'long'] as const).map((value) => <button key={value} className={exposure === value ? 'selected' : ''} onClick={() => setExposure(value)}>{value === 'short' ? 'Short' : 'Long'}</button>)}</div></div>
          <button className="run-button" onClick={() => void runLivePair()} disabled={runState === 'running'}><span>{runState === 'running' ? '◌' : '▶'}</span>{runState === 'running' ? '运行中…' : '运行配对实验'}</button>
          <div className={`preset-note ${runState}`}><i />{runMessage}</div>
          {liveRunId && <Link className="share-link" href={`/runs/${liveRunId}`}>打开 30 天分享结果 ↗</Link>}
        </aside>

        <section className="panel tissue-panel">
          <div className="panel-title row-title"><span>02</span><div><b>组织状态 · 同 tick 对照</b><small>点击细胞检查跨层状态</small></div><div className="field-tabs">{(['stress', 'signal', 'resource_level'] as const).map((name) => <button key={name} className={field === name ? 'selected' : ''} onClick={() => setField(name)}>{name === 'stress' ? '压力' : name === 'signal' ? '信号' : '资源'}</button>)}</div></div>
          <div className="tissue-compare">
            <article className="tissue-card"><div className="tissue-label"><b>{baseline.label}</b><span>{baseline.outcome}</span></div><TissueCanvas tick={baseTick} roles={bundle.roles} layout={bundle.layout} field={field} selectedCell={selectedCell} onSelect={setSelectedCell} label={`${baseline.label} 组织状态`} /></article>
            <article className="tissue-card"><div className="tissue-label"><b>{comparison.label}</b><span>Δ inflammation {delta(baseline.terminal_l4.inflammation, comparison.terminal_l4.inflammation)}</span></div><TissueCanvas tick={compareTick} roles={bundle.roles} layout={bundle.layout} field={field} selectedCell={selectedCell} onSelect={setSelectedCell} label={`${comparison.label} 组织状态`} /></article>
          </div>
          <div className="legend"><span><i className="tumor" />肿瘤细胞</span><span><i className="engineered" />工程巨噬细胞</span><span><i className="macrophage" />野生型巨噬细胞</span><span><i className="tcell" />CD8 T</span></div>
        </section>

        <aside className="panel inspector-panel">
          <div className="panel-title"><span>03</span><div><b>五层状态检查器</b><small>{selectedCell} · {roleName(bundle.roles[selectedCell])}</small></div></div>
          {baseCell && compareCell ? <div className="layer-stack">
            <LayerCard index={0} code="L0" name="基因调控" metric="signal_expression" left={baseCell.l0.signal_expression} right={compareCell.l0.signal_expression} />
            <LayerCard index={1} code="L1" name="分子状态" metric="signal_protein" left={baseCell.l1.signal_protein} right={compareCell.l1.signal_protein} />
            <LayerCard index={2} code="L2" name="细胞行为" metric="phase" text={`${baseCell.phase} → ${compareCell.phase}`} />
            <LayerCard index={3} code="L3" name="局部微环境" metric={`local ${field}`} left={baseCell.node[field]} right={compareCell.node[field]} />
            <LayerCard index={4} code="L4" name="宏观表型" metric="homeostasis" left={baseline.terminal_l4.homeostasis} right={comparison.terminal_l4.homeostasis} />
          </div> : <p className="empty-note">两个条件中没有同名 Cell。</p>}
          <div className="boundary"><b>科学边界</b><p>{bundle.boundary_note}</p></div>
        </aside>
      </section>

      <section className="panel timeline-panel">
        <div className="timeline-head"><div><b>跨尺度传播时间轴</b><small>tick {baseTick.t} · L0 更新和 L4 观测均显式标记</small></div><button className="play-button" onClick={() => setPlaying((value) => !value)}>{playing ? '暂停' : '播放'}</button><span>TICK {safeTick + 1} / {maximumTick + 1}</span></div>
        <input className="tick-range" type="range" min={0} max={maximumTick} value={safeTick} onChange={(event) => { setPlaying(false); setTickIndex(Number(event.target.value)); }} aria-label="实验 tick" />
        <div className="tick-flags"><span className={compareTick.l0_updated ? 'on' : ''}>L0 {compareTick.l0_updated ? 'UPDATED' : 'HELD'}</span><span className={compareTick.l4_observed ? 'on' : ''}>L4 {compareTick.l4_observed ? 'OBSERVED' : 'WAITING'}</span><span>perturbation events <b>{compareTick.audit.l0_perturbation_count}</b></span><span>transitions <b>{compareTick.audit.transition_count}</b></span></div>
        <div className="charts-grid">{l4Metrics.map(([metric, label]) => <MetricChart key={metric} baseline={baseline} comparison={comparison} metric={metric} label={label} />)}</div>
        <div className="endpoint-grid">{l4Metrics.map(([metric, label]) => <div key={metric}><span>{label}</span><b>{formatMetric(comparison.terminal_l4[metric])}</b><small className={(comparison.terminal_l4[metric] - baseline.terminal_l4[metric]) >= 0 ? 'positive' : 'negative'}>{delta(baseline.terminal_l4[metric], comparison.terminal_l4[metric])}</small></div>)}</div>
        <div className="audit-row"><span>experiment <code>{comparison.experiment_id}</code></span><span>history <code>{comparison.history_digest.slice(0, 16)}…</code></span><span>bundle <code>{bundle.bundle_digest.slice(0, 16)}…</code></span><span className="honest-result">Δ 只表示方向，不自动等于改善</span></div>
      </section>
      <section className="lab-footer-note"><b>{bundle.target_status}</b><span>{catalogEntry?.description ?? bundle.description}</span></section>
    </main>
  );
}

function LayerCard({ index, code, name, metric, left, right, text }: { index: number; code: string; name: string; metric: string; left?: number; right?: number; text?: string }) {
  return <div className={`layer-card layer-${index}`}><span>{code}</span><div><b>{name}</b><small>{metric}</small></div><strong>{text ?? `${formatMetric(left)} → ${formatMetric(right)}`}</strong></div>;
}
