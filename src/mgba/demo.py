"""Self-contained CAR-M demo export for offline stage presentation.

This module is experiment-observation infrastructure: it replays the frozen
CAR-M vertical-slice matrix in memory (no raw artifacts are written), packs the
seed-42 trajectories into a deterministic playbook JSON, and renders a single
self-contained HTML player with zero network dependencies. It never executes
or mutates any layer model beyond the normal frozen matrix run, and every
number in the playbook is rounded display precision; the raw matrix artifacts
remain the only source of truth.

Note on seeds: ``CausalExperimentConfig`` requires at least two seeds, so the
demo runs the frozen seed set ``(41, 42, 43)`` with ablations removed and
selects the seed-42 records for display. Each (condition, seed) run is
independently seeded, so the displayed trajectories are identical to a
hypothetical single-seed run.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .experiment import digest_payload
from .experiments import load_causal_config
from .reporting import _sha256
from .run_report import _L0_FIELDS, _L1_FIELDS, _L2_FIELDS, _L3_FIELDS, _L4_FIELDS
from .runner import MultirateRun, load_runner_config
from .scenarios.carm import (
    CompiledCarmScenario,
    build_carm_runners,
    compile_carm_scenario,
    load_carm_scenario_config,
    run_carm_matrix,
)
from .experiments import CausalMatrixResult

DEMO_PLAYBOOK_SCHEMA = "mgba-demo-playbook-0.2"
_DEMO_FILES_SCHEMA = "mgba-demo-files-0.1"
_DEMO_SEED = 42
_DEMO_TITLE = "M-GBA CAR-M 跨尺度研究观察台"

# Fixed scientific boundary statement shown verbatim in the player footer.
# The negative baseline wording is load-bearing and must not be softened.
BOUNDARY_NOTE = (
    "全部指标为无量纲 reference-model 代理，不是临床预测；"
    "当前冻结高剂量条件炎症上升且负担代理略升，作为负面基线原样保留。"
    "L3 tissue_damage 是模型内部代理，混合肿瘤活力与免疫细胞损伤。"
)

# Deterministic layout: one ring per role, sorted cell ids per ring.
_ROLE_RING_ORDER = (
    "tumor",
    "engineered_macrophage",
    "wild_type_macrophage",
    "cd8_t_cell",
)
_ROLE_RADII = (0.16, 0.34, 0.42, 0.48)
_RING_ANGLE_OFFSET = 0.37


@dataclass(frozen=True, slots=True)
class DemoExportPaths:
    root: Path
    playbook: Path
    html: Path
    manifest: Path


def _round4(value: float) -> float:
    rounded = round(value, 4)
    # Normalize -0.0 so the playbook never emits a negative zero.
    return 0.0 if rounded == 0.0 else rounded


def _build_layout(role_map: dict[str, str]) -> dict[str, list[float]]:
    layout: dict[str, list[float]] = {}
    for ring_index, (role, radius) in enumerate(
        zip(_ROLE_RING_ORDER, _ROLE_RADII)
    ):
        members = sorted(
            cell_id for cell_id, cell_role in role_map.items() if cell_role == role
        )
        count = len(members)
        for index, cell_id in enumerate(members):
            angle = 2.0 * math.pi * index / count + ring_index * _RING_ANGLE_OFFSET
            layout[cell_id] = [
                _round4(0.5 + radius * math.cos(angle)),
                _round4(0.5 + radius * math.sin(angle)),
            ]
    return layout


def _condition_ticks(run: MultirateRun) -> list[dict[str, Any]]:
    ticks: list[dict[str, Any]] = []
    for tick in run.ticks:
        if (tick.l4 is not None) != tick.l4_observed:
            raise ValueError("run tick l4 observation flag is inconsistent")
        cells: dict[str, Any] = {}
        for l0, l1, l2, node in zip(tick.l0, tick.l1, tick.l2, tick.l3.nodes):
            if not (l0.cell_id == l1.cell_id == l2.cell_id == node.cell_id):
                raise ValueError("run tick cell identities are not aligned")
            cells[l0.cell_id] = {
                "phase": l2.phase.value,
                "viability": _round4(l2.viability),
                "activation": _round4(l2.activation),
                "stress_load": _round4(l2.stress_load),
                "l0": {field: _round4(getattr(l0, field)) for field in _L0_FIELDS},
                "l1": {field: _round4(getattr(l1, field)) for field in _L1_FIELDS},
                "node": {
                    "resource_level": _round4(node.resource_level),
                    "signal": _round4(node.signal),
                    "stress": _round4(node.stress),
                },
            }
        ticks.append(
            {
                "t": tick.logical_time,
                "l0_updated": tick.l0_updated,
                "l4_observed": tick.l4_observed,
                "audit": {
                    "transition_count": len(tick.transitions),
                    "l0_perturbation_count": len(tick.l0_perturbation_events),
                    "layer_paths": [
                        f"{event.source_layer.value}->{event.target_layer.value}"
                        for event in tick.transitions
                    ],
                },
                "cells": cells,
                "l3": {
                    field: _round4(getattr(tick.l3, field)) for field in _L3_FIELDS
                },
                "l4": (
                    None
                    if tick.l4 is None
                    else {
                        field: _round4(getattr(tick.l4, field))
                        for field in _L4_FIELDS
                    }
                ),
            }
        )
    return ticks


def build_demo_playbook(
    result: CausalMatrixResult,
    compiled: CompiledCarmScenario,
    *,
    seed: int = _DEMO_SEED,
) -> dict[str, Any]:
    """Pack the seed-``seed`` condition trajectories into a display playbook."""
    expected_conditions = (
        "baseline",
        *(item.condition_id for item in result.config.perturbations),
    )
    records = tuple(record for record in result.records if record.seed == seed)
    if tuple(record.condition_id for record in records) != expected_conditions:
        raise ValueError("demo records are incomplete for the display seed")
    role_map = {cell_id: role.value for cell_id, role in compiled.roles}
    conditions = []
    for record in records:
        run = record.run
        if len(run.ticks) != result.config.ticks:
            raise ValueError("demo run does not contain every configured tick")
        conditions.append(
            {
                "condition_id": record.condition_id,
                "experiment_id": run.manifest.experiment_id,
                "history_digest": run.history_digest,
                # The runner's terminal slow-clock observation is computed at
                # end_tick but is not part of the tick trace; it is the point
                # where the frozen matrix compares final L4 metrics.
                "terminal_l4": {
                    field: _round4(getattr(run.terminal_observation, field))
                    for field in _L4_FIELDS
                },
                "outcome": run.phenotype_window.outcome.value,
                "ticks": _condition_ticks(run),
            }
        )
    playbook: dict[str, Any] = {
        "schema_version": DEMO_PLAYBOOK_SCHEMA,
        "title": _DEMO_TITLE,
        "boundary_note": BOUNDARY_NOTE,
        "seed": seed,
        "roles": role_map,
        "layout": _build_layout(role_map),
        "edges": [[source, target] for source, target in compiled.scenario.edges],
        "observer": {
            "reference_condition": "baseline",
            "default_comparison_condition": "car_affinity_070",
            "field_layers": ["stress", "signal", "resource_level"],
            "spatial_semantics": (
                "deterministic role-ring observation layout; positions and heatmaps "
                "are derived display projections, not simulated physical coordinates"
            ),
            "legacy_reference": (
                "CAR-M Virtual Cell canvas, cytokine-field overlay, and experiment "
                "comparison interaction patterns"
            ),
        },
        "conditions": conditions,
    }
    playbook["playbook_digest"] = digest_payload(playbook)
    return playbook


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M-GBA CAR-M 跨尺度研究观察台</title>
<style>
:root { color-scheme: dark; font-family: Inter, system-ui, "Microsoft YaHei", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #06111f; color: #dbeafe; }
header { padding: 16px 20px 13px; background: linear-gradient(135deg, #071525, #0d2239); border-bottom: 1px solid #1e3a5f; }
header h1 { margin: 0; font-size: 22px; letter-spacing: .02em; }
header p { margin: 5px 0 11px; color: #93c5fd; font-size: 12px; }
#tabs, #field-controls { display: flex; gap: 7px; flex-wrap: wrap; }
button { border: 1px solid #315172; background: #10263d; color: #bfdbfe; border-radius: 7px; padding: 6px 11px; cursor: pointer; }
button:hover { border-color: #60a5fa; }
button.active { background: #2563eb; border-color: #60a5fa; color: white; }
main { padding: 14px 18px 88px; max-width: 1720px; margin: 0 auto; }
.panel { background: #0a1a2b; border: 1px solid #1d3854; border-radius: 11px; padding: 12px; box-shadow: 0 10px 25px rgba(0,0,0,.16); }
.panel h2 { margin: 0 0 7px; font-size: 14px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.canvas-grid { display: grid; grid-template-columns: repeat(2, minmax(320px, 1fr)); gap: 12px; }
.canvas-wrap canvas { display: block; width: 100%; max-width: 660px; height: auto; margin: 8px auto 0; background: #071321; border-radius: 8px; }
.condition-name { color: #7dd3fc; font-size: 12px; font-family: ui-monospace, monospace; }
.analysis-grid { display: grid; grid-template-columns: minmax(520px, 1.4fr) minmax(360px, 1fr); gap: 12px; margin-top: 12px; align-items: start; }
.stack { display: grid; gap: 12px; }
#l4charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(205px, 1fr)); gap: 7px; }
#l4charts figure { margin: 0; padding: 7px; background: #071626; border: 1px solid #16334e; border-radius: 8px; }
#l4charts canvas { width: 100%; height: auto; }
#l4charts figcaption { font-size: 11px; color: #93c5fd; }
.legend { display: flex; gap: 14px; color: #9fb9d4; font-size: 11px; margin-bottom: 5px; }
.swatch { display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin-right: 4px; }
.hint { color: #7895b3; font-size: 11px; line-height: 1.5; }
.group-title { margin: 10px 0 4px; font-size: 12px; font-weight: 700; color: #bae6fd; }
.table-scroll { max-height: 410px; overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th, td { padding: 4px 6px; border-bottom: 1px solid #18334e; text-align: right; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; color: #a8c3df; }
th { color: #7dd3fc; position: sticky; top: 0; background: #0a1a2b; }
.delta-pos { color: #67e8f9; } .delta-neg { color: #fca5a5; } .delta-zero { color: #94a3b8; }
.audit-line { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; border-bottom: 1px solid #17324b; font-size: 11px; }
.audit-line span:first-child { color: #8aa7c4; }
.role-legend { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 7px; font-size: 10px; color: #8eabc8; }
.role-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
#controls { position: fixed; left: 0; right: 0; bottom: 0; z-index: 5; display: flex; align-items: center; gap: 9px; padding: 9px 18px; background: rgba(6,17,31,.96); border-top: 1px solid #27445f; backdrop-filter: blur(8px); }
#tickslider { flex: 1; min-width: 160px; }
#ticklabel { min-width: 86px; font-size: 12px; font-family: ui-monospace, monospace; }
footer { padding: 10px 18px 86px; max-width: 1720px; margin: 0 auto; color: #7895b3; font-size: 11px; line-height: 1.55; }
footer code { color: #bae6fd; }
.boundary { border-left: 4px solid #f59e0b; padding-left: 10px; margin-top: 7px; color: #fcd34d; }
@media (max-width: 980px) { .canvas-grid, .analysis-grid { grid-template-columns: 1fr; } #controls { flex-wrap: wrap; } }
</style>
</head>
<body>
<header>
<h1 id="title"></h1>
<p>双轨同步对照：左侧冻结 baseline，右侧选择干预；所有画面均来自同一 seed、同一 tick 的正式 raw trajectory。</p>
<div id="tabs"></div>
</header>
<main>
<section class="canvas-grid">
  <div class="panel canvas-wrap">
    <div class="panel-head"><div><h2>参考轨迹</h2><div class="condition-name" id="reference-label"></div></div><span class="hint">冻结对照</span></div>
    <canvas id="tissue-reference" width="620" height="620"></canvas>
  </div>
  <div class="panel canvas-wrap">
    <div class="panel-head"><div><h2>干预轨迹</h2><div class="condition-name" id="comparison-label"></div></div><span class="hint">同 tick 对齐</span></div>
    <canvas id="tissue-comparison" width="620" height="620"></canvas>
  </div>
</section>
<div class="role-legend" id="role-legend"></div>
<section class="analysis-grid">
  <div class="stack">
    <div class="panel">
      <div class="panel-head"><div><h2>L4 宏观表型双轨曲线</h2><div class="legend"><span><i class="swatch" style="background:#64748b"></i>baseline</span><span><i class="swatch" style="background:#38bdf8"></i>当前干预</span></div></div><span class="hint">慢时钟观测 + tick 30 终末观察</span></div>
      <div id="l4charts"></div>
    </div>
    <div class="panel">
      <h2>细胞跨层差异检查器</h2>
      <div id="inspector"><p class="hint">点击任一组织画布中的细胞，查看同一 cell 在 baseline 与干预下的 L0→L1→L2→局部 L3 差异。</p></div>
    </div>
  </div>
  <div class="stack">
    <div class="panel"><h2>L3 组织状态对照（当前 tick）</h2><div id="l3-compare"></div></div>
    <div class="panel"><h2>L4 终末结果对照</h2><div id="endpoint-compare"></div></div>
    <div class="panel"><h2>当前 tick 审计</h2><div id="audit"></div></div>
    <div class="panel">
      <div class="panel-head"><div><h2>L3 显示场</h2><p class="hint">由固定布局上的节点值做径向投影，仅用于观察；不是连续物理场求解。</p></div></div>
      <div id="field-controls">
        <button class="field active" data-field="stress">压力</button>
        <button class="field" data-field="signal">信号</button>
        <button class="field" data-field="resource_level">资源</button>
        <button class="field" data-field="none">关闭</button>
      </div>
    </div>
  </div>
</section>
</main>
<div id="controls">
<button id="playbtn">播放</button>
<button class="speed active" data-speed="1">1×</button>
<button class="speed" data-speed="2">2×</button>
<button class="speed" data-speed="4">4×</button>
<input id="tickslider" type="range" min="1" max="1" step="1" value="1">
<span id="ticklabel"></span>
</div>
<footer><div id="provenance"></div><div class="boundary" id="boundary"></div></footer>
<script>window.MGBA_PLAYBOOK = __MGBA_PLAYBOOK_JSON__;</script>
<script>
"use strict";
const PB = window.MGBA_PLAYBOOK;
const TICKS = PB.conditions[0].ticks.length;
const ROLE_COLORS = {tumor:"#ef4444", engineered_macrophage:"#3b82f6", wild_type_macrophage:"#06b6d4", cd8_t_cell:"#a855f7"};
const ROLE_NAMES = {tumor:"肿瘤细胞", engineered_macrophage:"工程巨噬细胞", wild_type_macrophage:"野生巨噬细胞", cd8_t_cell:"CD8 T 细胞"};
const PHASE_NAMES = {quiescent:"静息", activated:"激活", repairing:"修复", stressed:"应激", dead:"死亡"};
const COND_LABELS = {baseline:"baseline 无治疗", car_off_000:"CAR 信号关闭", car_affinity_070:"CAR 标准剂量 0.7", car_max_100:"CAR 最大剂量 1.0"};
const L0_NAMES = {damage_response:"损伤响应",signal_expression:"信号表达",repair_expression:"修复表达",metabolic_expression:"代谢表达",death_expression:"死亡表达",negative_feedback_expression:"负反馈表达"};
const L1_NAMES = {damage_receptor:"损伤受体",signal_protein:"信号蛋白",repair_protein:"修复蛋白",metabolic_capacity:"代谢能力",death_effector:"死亡效应子",feedback_inhibitor:"反馈抑制子"};
const L2_NAMES = {viability:"活力",activation:"激活",stress_load:"应激负荷"};
const NODE_NAMES = {resource_level:"局部资源",signal:"局部信号",stress:"局部压力"};
const L3_NAMES = {mean_resource:"平均资源",tissue_damage:"组织损伤",repair_activity:"修复活性",mean_activation:"平均激活",mean_signal:"平均信号",dead_fraction:"死亡比例"};
const L4_NAMES = {vitality:"活力",damage_burden:"损伤负担",inflammation:"炎症",homeostasis:"稳态",recovery_capacity:"恢复能力"};
const refIndex = Math.max(0, PB.conditions.findIndex(c => c.condition_id === PB.observer.reference_condition));
const defaultIndex = Math.max(0, PB.conditions.findIndex(c => c.condition_id === PB.observer.default_comparison_condition));
const state = {cond:defaultIndex,tick:1,playing:false,speed:1,selected:null,timer:null,field:"stress"};
const canvases = [document.getElementById("tissue-reference"), document.getElementById("tissue-comparison")];

function condition(i){ return PB.conditions[i]; }
function tickData(i){ return condition(i).ticks[state.tick-1]; }
function clamp(v){ return Math.min(1,Math.max(0,v)); }
function signed(v){ return (v>0?"+":"")+v.toFixed(4); }
function deltaClass(v){ return Math.abs(v)<.00005?"delta-zero":(v>0?"delta-pos":"delta-neg"); }
function esc(v){ return String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function fieldColor(key){ return key==="stress"?[239,68,68]:key==="signal"?[14,165,233]:[34,197,94]; }
function drawField(g,canvas,data){
  if(state.field==="none") return;
  const rgb=fieldColor(state.field);
  for(const id of Object.keys(PB.layout)){
    const value=data.cells[id].node[state.field];
    const [nx,ny]=PB.layout[id], x=nx*canvas.width, y=ny*canvas.height, radius=55+45*value;
    const grad=g.createRadialGradient(x,y,0,x,y,radius);
    grad.addColorStop(0,`rgba(${rgb[0]},${rgb[1]},${rgb[2]},${(.34*value).toFixed(3)})`);
    grad.addColorStop(1,`rgba(${rgb[0]},${rgb[1]},${rgb[2]},0)`);
    g.fillStyle=grad; g.fillRect(x-radius,y-radius,radius*2,radius*2);
  }
}
function drawTissue(canvas,index){
  const g=canvas.getContext("2d"), data=tickData(index), w=canvas.width, h=canvas.height;
  g.clearRect(0,0,w,h); g.fillStyle="#071321"; g.fillRect(0,0,w,h); drawField(g,canvas,data);
  g.strokeStyle="rgba(148,163,184,.11)"; g.lineWidth=1;
  for(const [a,b] of PB.edges){ const pa=PB.layout[a],pb=PB.layout[b]; g.beginPath();g.moveTo(pa[0]*w,pa[1]*h);g.lineTo(pb[0]*w,pb[1]*h);g.stroke(); }
  for(const id of Object.keys(PB.layout)){
    const cell=data.cells[id],[x,y]=PB.layout[id],dead=cell.phase==="dead",r=dead?3.4:4.5+8*cell.viability;
    g.beginPath();g.arc(x*w,y*h,r,0,Math.PI*2);g.fillStyle=dead?"#64748b":ROLE_COLORS[PB.roles[id]];g.fill();
    if(cell.phase==="stressed"){g.strokeStyle="#fb923c";g.lineWidth=2.4;g.stroke();}
    if(state.selected===id){g.strokeStyle="#f8fafc";g.lineWidth=2.2;g.stroke();}
  }
}
function observations(c,key){
  const points=c.ticks.filter(t=>t.l4!==null&&t.t<=state.tick).map(t=>({t:t.t,v:t.l4[key]}));
  if(state.tick>=TICKS) points.push({t:TICKS,v:c.terminal_l4[key]});
  return points;
}
function drawSeries(g,points,color,x,y){
  if(!points.length)return;g.strokeStyle=color;g.lineWidth=2;g.beginPath();
  points.forEach((p,i)=>{if(i===0)g.moveTo(x(p.t),y(p.v));else g.lineTo(x(p.t),y(p.v));});g.stroke();
  const p=points[points.length-1];g.fillStyle=color;g.beginPath();g.arc(x(p.t),y(p.v),2.8,0,Math.PI*2);g.fill();
}
function drawL4(){
  for(const key of Object.keys(L4_NAMES)){
    const c=document.getElementById("l4-"+key),g=c.getContext("2d"),w=c.width,h=c.height,pL=24,pB=14,pT=6,pR=4;
    g.clearRect(0,0,w,h);g.strokeStyle="#28445f";g.beginPath();g.moveTo(pL,pT);g.lineTo(pL,h-pB);g.lineTo(w-pR,h-pB);g.stroke();
    const x=t=>pL+(t-1)/(TICKS-1)*(w-pL-pR), y=v=>pT+(1-clamp(v))*(h-pT-pB);
    drawSeries(g,observations(condition(refIndex),key),"#64748b",x,y);drawSeries(g,observations(condition(state.cond),key),"#38bdf8",x,y);
  }
}
function comparisonTable(names,left,right){
  let h="<table><thead><tr><th>指标</th><th>baseline</th><th>干预</th><th>Δ</th></tr></thead><tbody>";
  for(const k of Object.keys(names)){const d=right[k]-left[k];h+=`<tr><td>${names[k]}</td><td>${left[k].toFixed(4)}</td><td>${right[k].toFixed(4)}</td><td class="${deltaClass(d)}">${signed(d)}</td></tr>`;}
  return h+"</tbody></table>";
}
function drawL3(){document.getElementById("l3-compare").innerHTML=comparisonTable(L3_NAMES,tickData(refIndex).l3,tickData(state.cond).l3);}
function drawEndpoint(){
  const a=condition(refIndex),b=condition(state.cond);
  document.getElementById("endpoint-compare").innerHTML=comparisonTable(L4_NAMES,a.terminal_l4,b.terminal_l4)+`<p class="hint">结局：baseline <b>${esc(a.outcome)}</b> · 干预 <b>${esc(b.outcome)}</b>。Δ 只表示有向差，不自动等于改善。</p>`;
}
function sectionRows(title,names,left,right){return `<div class="group-title">${title}</div>`+comparisonTable(names,left,right);}
function drawInspector(){
  const box=document.getElementById("inspector");if(!state.selected){box.innerHTML='<p class="hint">点击任一画布中的细胞，查看同一 cell 的跨条件差异。</p>';return;}
  const id=state.selected,a=tickData(refIndex).cells[id],b=tickData(state.cond).cells[id];
  box.innerHTML=`<div class="group-title">${esc(id)} · ${ROLE_NAMES[PB.roles[id]]} · 相位 ${PHASE_NAMES[a.phase]} → ${PHASE_NAMES[b.phase]}</div><div class="table-scroll">`+
    sectionRows("L2 细胞状态",L2_NAMES,a,b)+sectionRows("局部 L3 节点",NODE_NAMES,a.node,b.node)+sectionRows("L0 抽象表达",L0_NAMES,a.l0,b.l0)+sectionRows("L1 分子状态",L1_NAMES,a.l1,b.l1)+"</div>";
}
function drawAudit(){
  const t=tickData(state.cond),a=t.audit;
  const lines=[["逻辑时间",t.t],["L0 更新",t.l0_updated?"是":"保持"],["L4 观测",t.l4_observed?"是":"否"],["相邻转换事件",a.transition_count],["L0 扰动事件",a.l0_perturbation_count],["层路径",a.layer_paths.join(" · ")||"无"]];
  document.getElementById("audit").innerHTML=lines.map(x=>`<div class="audit-line"><span>${x[0]}</span><b>${esc(x[1])}</b></div>`).join("");
}
function drawFooter(){
  const c=condition(state.cond);document.getElementById("provenance").innerHTML=`干预 <code>${esc(c.condition_id)}</code> · experiment <code>${esc(c.experiment_id)}</code> · history <code>${c.history_digest.slice(0,16)}…</code> · seed ${PB.seed} · playbook <code>${PB.playbook_digest.slice(0,16)}…</code><br>显示语义：${esc(PB.observer.spatial_semantics)}。交互参考：${esc(PB.observer.legacy_reference)}。`;
}
function render(){
  drawTissue(canvases[0],refIndex);drawTissue(canvases[1],state.cond);drawL4();drawL3();drawEndpoint();drawInspector();drawAudit();drawFooter();
  document.getElementById("reference-label").textContent=COND_LABELS[condition(refIndex).condition_id]||condition(refIndex).condition_id;
  document.getElementById("comparison-label").textContent=COND_LABELS[condition(state.cond).condition_id]||condition(state.cond).condition_id;
  document.getElementById("tickslider").value=state.tick;document.getElementById("ticklabel").textContent=`tick ${state.tick} / ${TICKS}`;
  document.querySelectorAll("#tabs button").forEach((b,i)=>b.classList.toggle("active",i===state.cond));
}
function stopPlayback(){state.playing=false;if(state.timer!==null){clearInterval(state.timer);state.timer=null;}document.getElementById("playbtn").textContent="播放";}
function startPlayback(){if(state.tick>=TICKS)state.tick=1;state.playing=true;document.getElementById("playbtn").textContent="暂停";state.timer=setInterval(()=>{if(state.tick>=TICKS){stopPlayback();return;}state.tick++;render();},Math.round(650/state.speed));render();}
function bindCanvas(canvas){canvas.addEventListener("click",ev=>{const rect=canvas.getBoundingClientRect(),cx=(ev.clientX-rect.left)*canvas.width/rect.width,cy=(ev.clientY-rect.top)*canvas.height/rect.height;let best=null,bestDist=15;for(const id of Object.keys(PB.layout)){const p=PB.layout[id],d=Math.hypot(p[0]*canvas.width-cx,p[1]*canvas.height-cy);if(d<bestDist){best=id;bestDist=d;}}state.selected=best;render();});}
function init(){
  document.getElementById("title").textContent=PB.title;
  PB.conditions.forEach((c,i)=>{const b=document.createElement("button");b.textContent=COND_LABELS[c.condition_id]||c.condition_id;b.addEventListener("click",()=>{state.cond=i;render();});document.getElementById("tabs").appendChild(b);});
  for(const key of Object.keys(L4_NAMES)){const f=document.createElement("figure");f.innerHTML=`<canvas id="l4-${key}" width="230" height="100"></canvas><figcaption>${L4_NAMES[key]} (${key})</figcaption>`;document.getElementById("l4charts").appendChild(f);}
  document.getElementById("role-legend").innerHTML=Object.keys(ROLE_NAMES).map(k=>`<span><i class="role-dot" style="background:${ROLE_COLORS[k]}"></i>${ROLE_NAMES[k]}</span>`).join("");
  const slider=document.getElementById("tickslider");slider.max=TICKS;slider.addEventListener("input",()=>{stopPlayback();state.tick=Number(slider.value);render();});
  document.getElementById("playbtn").addEventListener("click",()=>state.playing?stopPlayback():startPlayback());
  document.querySelectorAll(".speed").forEach(b=>b.addEventListener("click",()=>{state.speed=Number(b.dataset.speed);document.querySelectorAll(".speed").forEach(x=>x.classList.toggle("active",x===b));if(state.playing){stopPlayback();startPlayback();}}));
  document.querySelectorAll(".field").forEach(b=>b.addEventListener("click",()=>{state.field=b.dataset.field;document.querySelectorAll(".field").forEach(x=>x.classList.toggle("active",x===b));render();}));
  canvases.forEach(bindCanvas);document.getElementById("boundary").textContent=PB.boundary_note;render();
}
init();
</script>
</body>
</html>
"""


def write_demo_html(playbook: dict[str, Any]) -> str:
    """Render the self-contained offline HTML player for one playbook."""
    blob = json.dumps(playbook, ensure_ascii=False, separators=(",", ":"))
    # Defensive: the playbook contains only numbers and fixed-vocabulary
    # strings, but never allow a literal "</" inside the script block.
    blob = blob.replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__MGBA_PLAYBOOK_JSON__", blob)


def export_carm_demo(
    *,
    scenario_config: str | Path = "configs/scenarios/carm/high_immune_her2.json",
    matrix_config: str | Path = "configs/experiments/carm_vertical_slice.json",
    runner_config: str | Path = "configs/runner_reference.json",
    l0_config: str | Path = "configs/layers/l0_reference_grn.json",
    l1_config: str | Path = "configs/layers/l1_reference_molecular.json",
    l4_config: str | Path = "configs/layers/l4_reference_phenotype.json",
    output_dir: str | Path = "artifacts/demo",
) -> DemoExportPaths:
    """Replay the frozen CAR-M matrix in memory and write the demo files.

    Writes ``carm-playbook.json``, ``mgba-carm-demo.html`` and
    ``demo-manifest.json`` into ``output_dir``. All content is a deterministic
    function of the frozen configs; existing files are overwritten with
    byte-identical content. No raw run artifacts are written.
    """
    output = Path(output_dir).resolve()
    if "raw" in output.parts:
        raise ValueError(
            "refusing to write demo files inside a raw artifact directory; "
            "pass --output-dir explicitly"
        )
    compiled = compile_carm_scenario(load_carm_scenario_config(scenario_config))
    full_config = load_causal_config(matrix_config)
    # CausalExperimentConfig requires >=2 seeds, so keep the frozen seed set
    # and drop only the ablations; the playbook selects the display seed.
    demo_config = replace(full_config, ablations=())
    runners = build_carm_runners(
        compiled,
        demo_config,
        runner_config=load_runner_config(runner_config),
        l0_config=l0_config,
        l1_config=l1_config,
        l4_config=l4_config,
    )
    result = run_carm_matrix(compiled, demo_config, runners=runners)
    playbook = build_demo_playbook(result, compiled)
    html_text = write_demo_html(playbook)
    output.mkdir(parents=True, exist_ok=True)
    paths = DemoExportPaths(
        root=output,
        playbook=output / "carm-playbook.json",
        html=output / "mgba-carm-demo.html",
        manifest=output / "demo-manifest.json",
    )
    paths.playbook.write_text(
        json.dumps(playbook, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.html.write_text(html_text, encoding="utf-8")
    manifest_payload = {
        "schema_version": _DEMO_FILES_SCHEMA,
        "files": {
            path.name: _sha256(path) for path in (paths.html, paths.playbook)
        },
        "playbook_digest": playbook["playbook_digest"],
    }
    paths.manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return paths
