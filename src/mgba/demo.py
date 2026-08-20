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

DEMO_PLAYBOOK_SCHEMA = "mgba-demo-playbook-0.1"
_DEMO_FILES_SCHEMA = "mgba-demo-files-0.1"
_DEMO_SEED = 42
_DEMO_TITLE = "CAR-M 虚拟细胞治疗跨尺度演示"

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
                "l4_observed": tick.l4_observed,
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
        "conditions": conditions,
    }
    playbook["playbook_digest"] = digest_payload(playbook)
    return playbook


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M-GBA CAR-M 跨尺度演示</title>
<style>
:root { color-scheme: light; font-family: system-ui, "Microsoft YaHei", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #f8fafc; color: #0f172a; }
header { padding: 10px 16px; background: #0f172a; color: #f8fafc; }
header h1 { margin: 0 0 8px; font-size: 18px; font-weight: 600; }
#tabs { display: flex; gap: 8px; flex-wrap: wrap; }
#tabs button { border: 1px solid #475569; background: #1e293b; color: #e2e8f0; border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; }
#tabs button.active { background: #2563eb; border-color: #2563eb; color: #fff; }
main { display: flex; gap: 16px; padding: 12px 16px; align-items: flex-start; flex-wrap: wrap; }
.panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; }
.panel h2 { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
#tissue { display: block; }
#side { display: flex; flex-direction: column; gap: 12px; width: 460px; }
#l4charts { display: flex; flex-wrap: wrap; gap: 8px; }
#l4charts figure { margin: 0; }
#l4charts figcaption { font-size: 12px; color: #475569; }
.bar-row { display: flex; align-items: center; gap: 8px; margin: 2px 0; font-size: 12px; }
.bar-row .name { width: 118px; text-align: right; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-row .track { flex: 1; height: 10px; background: #e2e8f0; border-radius: 5px; overflow: hidden; }
.bar-row .fill { height: 100%; background: #2563eb; }
.bar-row .val { width: 48px; font-variant-numeric: tabular-nums; }
#controls { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #fff; border-top: 1px solid #e2e8f0; position: sticky; bottom: 0; }
#controls button { border: 1px solid #cbd5e1; background: #f1f5f9; border-radius: 6px; padding: 6px 14px; font-size: 13px; cursor: pointer; }
#controls button.active { background: #2563eb; border-color: #2563eb; color: #fff; }
#tickslider { flex: 1; }
#ticklabel { font-variant-numeric: tabular-nums; font-size: 14px; min-width: 72px; }
footer { padding: 10px 16px 18px; font-size: 12px; color: #475569; line-height: 1.6; }
footer code { font-family: ui-monospace, monospace; }
.boundary { border-left: 4px solid #ca8a04; padding-left: 10px; margin-top: 6px; }
.hint { color: #94a3b8; font-size: 12px; }
.group-title { font-size: 12px; font-weight: 600; color: #334155; margin: 8px 0 2px; }
</style>
</head>
<body>
<header>
<h1 id="title"></h1>
<div id="tabs"></div>
</header>
<main>
<div class="panel">
<h2>L3 组织画布（点击细胞查看 L0→L2 级联）</h2>
<canvas id="tissue" width="640" height="640"></canvas>
</div>
<div id="side">
<div class="panel">
<h2>L4 宏观表型（慢时钟观测，随 tick 推进）</h2>
<p class="hint">观测点：tick 1/11/21，末点为 tick 30 终末观测（冻结矩阵的最终指标比较点）。</p>
<div id="l4charts"></div>
</div>
<div class="panel">
<h2>L3 组织场均值（当前 tick）</h2>
<div id="l3bars"></div>
</div>
<div class="panel">
<h2>细胞检查器（L0 基因 → L1 分子 → L2 状态）</h2>
<div id="inspector"><p class="hint">点击左侧画布中的细胞圆点，查看该细胞当前 tick 的 L0 六基因、L1 六分子与 L2 三项状态。</p></div>
</div>
</div>
</main>
<div id="controls">
<button id="playbtn">播放</button>
<button class="speed" data-speed="1">1×</button>
<button class="speed" data-speed="2">2×</button>
<button class="speed" data-speed="4">4×</button>
<input id="tickslider" type="range" min="1" max="1" step="1" value="1">
<span id="ticklabel"></span>
</div>
<footer>
<div id="provenance"></div>
<div class="boundary" id="boundary"></div>
</footer>
<script>
window.MGBA_PLAYBOOK = __MGBA_PLAYBOOK_JSON__;
</script>
<script>
"use strict";
const PB = window.MGBA_PLAYBOOK;
const TICKS = PB.conditions[0].ticks.length;
const ROLE_COLORS = {tumor: "#dc2626", engineered_macrophage: "#2563eb", wild_type_macrophage: "#0891b2", cd8_t_cell: "#7c3aed"};
const ROLE_NAMES = {tumor: "肿瘤细胞", engineered_macrophage: "工程巨噬细胞", wild_type_macrophage: "野生巨噬细胞", cd8_t_cell: "CD8 T 细胞"};
const PHASE_NAMES = {quiescent: "静息", activated: "激活", repairing: "修复", stressed: "应激", dead: "死亡"};
const COND_LABELS = {baseline: "baseline 无治疗", car_off_000: "car_off_000 工程细胞无信号", car_affinity_070: "car_affinity_070 标准剂量", car_max_100: "car_max_100 最大剂量"};
const L0_NAMES = {damage_response: "损伤响应", signal_expression: "信号表达", repair_expression: "修复表达", metabolic_expression: "代谢表达", death_expression: "死亡表达", negative_feedback_expression: "负反馈表达"};
const L1_NAMES = {damage_receptor: "损伤受体", signal_protein: "信号蛋白", repair_protein: "修复蛋白", metabolic_capacity: "代谢能力", death_effector: "死亡效应子", feedback_inhibitor: "反馈抑制子"};
const L2_NAMES = {viability: "活力", activation: "激活", stress_load: "应激负荷"};
const L3_NAMES = {mean_resource: "平均资源", tissue_damage: "组织损伤", repair_activity: "修复活性", mean_activation: "平均激活", mean_signal: "平均信号", dead_fraction: "死亡比例"};
const L4_NAMES = {vitality: "活力", damage_burden: "损伤负担", inflammation: "炎症", homeostasis: "稳态", recovery_capacity: "恢复能力"};
const L4_KEYS = Object.keys(L4_NAMES);
const state = {cond: 0, tick: 1, playing: false, speed: 1, selected: null, timer: null};
const canvas = document.getElementById("tissue");
const ctx = canvas.getContext("2d");
const W = canvas.width, H = canvas.height;

function cond() { return PB.conditions[state.cond]; }
function tickData() { return cond().ticks[state.tick - 1]; }
function px(x) { return x * W; }
function py(y) { return y * H; }

function drawTissue() {
  const data = tickData();
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "rgba(100,116,139,0.08)";
  ctx.lineWidth = 1;
  for (const [a, b] of PB.edges) {
    const pa = PB.layout[a], pb = PB.layout[b];
    ctx.beginPath(); ctx.moveTo(px(pa[0]), py(pa[1])); ctx.lineTo(px(pb[0]), py(pb[1])); ctx.stroke();
  }
  for (const id of Object.keys(PB.layout)) {
    const cell = data.cells[id];
    const [x, y] = PB.layout[id];
    const dead = cell.phase === "dead";
    const r = dead ? 3.5 : 4 + 8 * cell.viability;
    ctx.beginPath();
    ctx.arc(px(x), py(y), r, 0, 2 * Math.PI);
    ctx.fillStyle = dead ? "#9ca3af" : ROLE_COLORS[PB.roles[id]];
    ctx.fill();
    if (cell.phase === "stressed") { ctx.strokeStyle = "#ea580c"; ctx.lineWidth = 2.5; ctx.stroke(); }
    if (state.selected === id) { ctx.strokeStyle = "#0f172a"; ctx.lineWidth = 2; ctx.stroke(); }
  }
}

function drawL4() {
  const data = cond();
  for (const key of L4_KEYS) {
    const c = document.getElementById("l4-" + key);
    const g = c.getContext("2d");
    const w = c.width, h = c.height, padL = 26, padB = 14, padT = 6, padR = 4;
    g.clearRect(0, 0, w, h);
    g.strokeStyle = "#cbd5e1"; g.lineWidth = 1;
    g.beginPath(); g.moveTo(padL, padT); g.lineTo(padL, h - padB); g.lineTo(w - padR, h - padB); g.stroke();
    g.fillStyle = "#94a3b8"; g.font = "9px sans-serif";
    g.fillText("1", 8, padT + 6); g.fillText("0", 8, h - padB);
    const obs = data.ticks.filter(t => t.l4 !== null && t.t <= state.tick).map(t => ({t: t.t, v: t.l4[key]}));
    if (state.tick >= TICKS && data.terminal_l4) obs.push({t: TICKS, v: data.terminal_l4[key]});
    const x = t => padL + (t - 1) / (TICKS - 1) * (w - padL - padR);
    const y = v => padT + (1 - Math.min(1, Math.max(0, v))) * (h - padT - padB);
    if (obs.length > 0) {
      g.strokeStyle = "#2563eb"; g.lineWidth = 2; g.beginPath();
      obs.forEach((p, i) => { const vx = x(p.t), vy = y(p.v); if (i === 0) g.moveTo(vx, vy); else g.lineTo(vx, vy); });
      g.stroke();
      const last = obs[obs.length - 1];
      g.fillStyle = "#2563eb"; g.beginPath(); g.arc(x(last.t), y(last.v), 3, 0, 2 * Math.PI); g.fill();
      g.fillStyle = "#0f172a"; g.font = "11px sans-serif";
      g.fillText(last.v.toFixed(3), Math.min(x(last.t) + 5, w - 34), y(last.v) - 4);
    } else {
      g.fillStyle = "#94a3b8"; g.font = "10px sans-serif"; g.fillText("尚无观测", padL + 6, padT + 12);
    }
  }
}

function barRow(name, value, color) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return '<div class="bar-row"><span class="name">' + name + '</span>' +
    '<span class="track"><span class="fill" style="width:' + pct + '%;background:' + color + '"></span></span>' +
    '<span class="val">' + value.toFixed(3) + "</span></div>";
}

function drawL3() {
  const l3 = tickData().l3;
  document.getElementById("l3bars").innerHTML =
    Object.keys(L3_NAMES).map(k => barRow(L3_NAMES[k], l3[k], "#0891b2")).join("");
}

function drawInspector() {
  const box = document.getElementById("inspector");
  if (!state.selected) {
    box.innerHTML = '<p class="hint">点击左侧画布中的细胞圆点，查看该细胞当前 tick 的 L0 六基因、L1 六分子与 L2 三项状态。</p>';
    return;
  }
  const id = state.selected;
  const cell = tickData().cells[id];
  let htmlText = '<div class="group-title">' + id + " · " + ROLE_NAMES[PB.roles[id]] + " · 相位：" + PHASE_NAMES[cell.phase] + "</div>";
  htmlText += '<div class="group-title">L2 细胞状态</div>';
  for (const k of Object.keys(L2_NAMES)) htmlText += barRow(L2_NAMES[k], cell[k], "#16a34a");
  htmlText += '<div class="group-title">L0 抽象基因表达</div>';
  for (const k of Object.keys(L0_NAMES)) htmlText += barRow(L0_NAMES[k], cell.l0[k], "#7c3aed");
  htmlText += '<div class="group-title">L1 分子状态</div>';
  for (const k of Object.keys(L1_NAMES)) htmlText += barRow(L1_NAMES[k], cell.l1[k], "#ca8a04");
  box.innerHTML = htmlText;
}

function drawFooter() {
  const c = cond();
  document.getElementById("provenance").innerHTML =
    "条件 <code>" + c.condition_id + "</code> · experiment <code>" + c.experiment_id +
    "</code> · history <code>" + c.history_digest.slice(0, 16) + "…</code> · 展示种子 " + PB.seed +
    " · playbook <code>" + PB.playbook_digest.slice(0, 16) + "…</code>";
}

function render() {
  drawTissue(); drawL4(); drawL3(); drawInspector(); drawFooter();
  document.getElementById("tickslider").value = state.tick;
  document.getElementById("ticklabel").textContent = "tick " + state.tick + " / " + TICKS;
  document.querySelectorAll("#tabs button").forEach((b, i) => b.classList.toggle("active", i === state.cond));
}

function stopPlayback() {
  state.playing = false;
  if (state.timer !== null) { clearInterval(state.timer); state.timer = null; }
  document.getElementById("playbtn").textContent = "播放";
}

function startPlayback() {
  if (state.tick >= TICKS) state.tick = 1;
  state.playing = true;
  document.getElementById("playbtn").textContent = "暂停";
  state.timer = setInterval(() => {
    if (state.tick >= TICKS) { stopPlayback(); return; }
    state.tick += 1;
    render();
  }, Math.round(700 / state.speed));
  render();
}

function init() {
  document.getElementById("title").textContent = PB.title;
  const tabs = document.getElementById("tabs");
  PB.conditions.forEach((c, i) => {
    const b = document.createElement("button");
    b.textContent = COND_LABELS[c.condition_id] || c.condition_id;
    b.addEventListener("click", () => { state.cond = i; render(); });
    tabs.appendChild(b);
  });
  const l4box = document.getElementById("l4charts");
  for (const key of L4_KEYS) {
    const fig = document.createElement("figure");
    fig.innerHTML = '<canvas id="l4-' + key + '" width="200" height="90"></canvas><figcaption>' + L4_NAMES[key] + " (" + key + ")</figcaption>";
    l4box.appendChild(fig);
  }
  const slider = document.getElementById("tickslider");
  slider.max = TICKS;
  slider.addEventListener("input", () => { stopPlayback(); state.tick = Number(slider.value); render(); });
  document.getElementById("playbtn").addEventListener("click", () => { state.playing ? stopPlayback() : startPlayback(); });
  document.querySelectorAll(".speed").forEach(b => b.addEventListener("click", () => {
    state.speed = Number(b.dataset.speed);
    document.querySelectorAll(".speed").forEach(x => x.classList.toggle("active", x === b));
    if (state.playing) { stopPlayback(); startPlayback(); }
  }));
  document.querySelector('.speed[data-speed="1"]').classList.add("active");
  canvas.addEventListener("click", ev => {
    const rect = canvas.getBoundingClientRect();
    const cx = (ev.clientX - rect.left) * (canvas.width / rect.width);
    const cy = (ev.clientY - rect.top) * (canvas.height / rect.height);
    let best = null, bestDist = 12;
    for (const id of Object.keys(PB.layout)) {
      const [x, y] = PB.layout[id];
      const d = Math.hypot(px(x) - cx, py(y) - cy);
      if (d < bestDist) { best = id; bestDist = d; }
    }
    state.selected = best;
    render();
  });
  document.getElementById("boundary").textContent = PB.boundary_note;
  render();
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
