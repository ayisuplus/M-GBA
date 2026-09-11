#!/usr/bin/env python3
"""M-GBA 效应稳健性探索性复分析（exploratory effect robustness re-analysis）。

探索性诊断，不构成确认性结论。

对已完成的配对矩阵实验 artifact（只读）做细胞级配对 bootstrap：
- 从每个 run 的终末 tick 提取逐细胞 L2 连续状态字段
  （stress_load / viability / activation）。
- 同一 seed 下每个干预/消融条件 vs baseline 做逐细胞差值（按 cell_id 交集对齐）。
- 先执行 seed 重复检测：条件内 3 个 seed 的逐细胞向量逐位比对；若为重放重复，
  合并为单次确定性实现，统计推断只在细胞维度进行。
- 每个配对输出：均值差、细胞级配对 bootstrap 95% 百分位 CI
  （随机流由 hashlib.sha256 对 (条件名, 字段, resample_index) 派生，完全确定性，
  不使用 random 模块全局状态）、方向一致率、效应驱动集中度（top 10% 细胞占比）。
- 从 raw 重算每 run 终末 L4 指标相对 baseline 的差值，与 derived/summary.json
  交叉核对；不一致时原样记录差异，不覆盖。

仅使用 Python 标准库；不 import mgba 内部 API；不修改任何输入 artifact。

用法：
    python scripts/exploratory_effect_robustness.py \
        --out artifacts/exploratory/<run-id> \
        --experiment <name>=<raw-dir> [--experiment ...] [--bootstrap 10000]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "mgba-exploratory-effect-robustness-0.1"

EXPLORATORY_DISCLAIMER = (
    "探索性诊断，不构成确认性结论。本分析中的置信区间是细胞维度配对重采样 "
    "(paired cell-level bootstrap) 的产物，刻画的是单次确定性实现内部逐细胞效应的"
    "离散程度，不是生物学重复或独立模拟重复带来的抽样不确定性；全部 seed 经逐位"
    "比对为重放重复（确定性重放），不构成统计重复。结果层级为探索性诊断，不支持"
    "任何确认性因果或稳健性主张。"
)

L2_FIELDS = ("stress_load", "viability", "activation")
L4_METRICS = (
    "vitality",
    "damage_burden",
    "inflammation",
    "homeostasis",
    "recovery_capacity",
)
BASELINE_CONDITION = "baseline"
CROSS_CHECK_TOL = 1e-9
SEED_FILE_RE = re.compile(r"^seed-(\d+)\.json$")
FLAT_FILE_RE = re.compile(r"^(.+)-seed-(\d+)\.json$")


# ---------------------------------------------------------------------------
# raw run 读取
# ---------------------------------------------------------------------------

def discover_runs(raw_dir: Path) -> dict:
    """返回 {condition: {seed: path}}。支持两种布局：

    - 嵌套: raw/<condition>/seed-<n>.json
    - 扁平: raw/<condition>-seed-<n>.json
    """
    runs: dict[str, dict[int, Path]] = {}
    subdirs = sorted(p for p in raw_dir.iterdir() if p.is_dir())
    if subdirs:
        for cond_dir in subdirs:
            cond = cond_dir.name
            for f in sorted(cond_dir.glob("seed-*.json")):
                m = SEED_FILE_RE.match(f.name)
                if m:
                    runs.setdefault(cond, {})[int(m.group(1))] = f
    else:
        for f in sorted(raw_dir.glob("*.json")):
            m = FLAT_FILE_RE.match(f.name)
            if m:
                runs.setdefault(m.group(1), {})[int(m.group(2))] = f
    if not runs:
        raise SystemExit(f"未在 {raw_dir} 发现任何 run JSON")
    return runs


def load_run(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def terminal_cells(run: dict) -> dict:
    """终末 tick 逐细胞 L2 状态：{cell_id: {field: float, 'phase': str}}"""
    ticks = run.get("ticks") or []
    if not ticks:
        raise ValueError("run 缺少 ticks")
    l2 = ticks[-1].get("l2") or []
    cells = {}
    for entry in l2:
        cid = entry["cell_id"]
        rec = {"phase": entry.get("phase")}
        for field in L2_FIELDS:
            rec[field] = float(entry[field])
        cells[cid] = rec
    return cells


def terminal_l4(run: dict) -> dict:
    obs = run.get("terminal_observation") or {}
    return {m: float(obs[m]) for m in L4_METRICS}


# ---------------------------------------------------------------------------
# 确定性 bootstrap
# ---------------------------------------------------------------------------

def _bootstrap_rng(namespace: str, resample_index: int) -> random.Random:
    key = f"{SCHEMA_VERSION}|{namespace}|{resample_index}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def bootstrap_mean_ci(diffs: list, namespace: str, resamples: int) -> dict:
    """配对 bootstrap：对差值向量做有放回重采样，取均值分布的 2.5%/97.5% 百分位。"""
    n = len(diffs)
    means = []
    for b in range(resamples):
        rng = _bootstrap_rng(namespace, b)
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()

    def percentile(p: float) -> float:
        pos = p * (len(means) - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return means[lo]
        frac = pos - lo
        return means[lo] * (1.0 - frac) + means[hi] * frac

    return {
        "ci95_lower": percentile(0.025),
        "ci95_upper": percentile(0.975),
        "resamples": resamples,
        "method": "paired-cell-bootstrap-percentile",
        "rng_derivation": "sha256(schema_version|experiment|condition|field|resample_index)[:8]",
    }


# ---------------------------------------------------------------------------
# 配对分析
# ---------------------------------------------------------------------------

def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def analyze_pair(base_cells: dict, cond_cells: dict, namespace: str,
                 resamples: int) -> dict:
    shared = sorted(set(base_cells) & set(cond_cells))
    result = {
        "n_cells_baseline": len(base_cells),
        "n_cells_condition": len(cond_cells),
        "n_cells_paired": len(shared),
        "baseline_only_cells": sorted(set(base_cells) - set(cond_cells)),
        "condition_only_cells": sorted(set(cond_cells) - set(base_cells)),
        "fields": {},
    }
    for field in L2_FIELDS:
        diffs = [cond_cells[c][field] - base_cells[c][field] for c in shared]
        mean_diff = sum(diffs) / len(diffs)
        mean_sign = _sign(mean_diff)
        n_match = sum(1 for d in diffs if _sign(d) == mean_sign and d != 0.0)
        n_zero = sum(1 for d in diffs if d == 0.0)
        n_oppose = len(diffs) - n_match - n_zero
        abs_diffs = sorted((abs(d) for d in diffs), reverse=True)
        total_abs = sum(abs_diffs)
        k = max(1, math.ceil(0.1 * len(abs_diffs)))
        concentration = (sum(abs_diffs[:k]) / total_abs) if total_abs > 0 else None
        boot = bootstrap_mean_ci(diffs, f"{namespace}|{field}", resamples)
        result["fields"][field] = {
            "mean_diff": mean_diff,
            "ci95_lower": boot["ci95_lower"],
            "ci95_upper": boot["ci95_upper"],
            "bootstrap_resamples": boot["resamples"],
            "ci_excludes_zero": not (boot["ci95_lower"] <= 0.0 <= boot["ci95_upper"]),
            "direction_consistency": (n_match / len(diffs)) if diffs else None,
            "n_cells_same_direction": n_match,
            "n_cells_opposite_direction": n_oppose,
            "n_cells_zero_diff": n_zero,
            "top10pct_abs_effect_share": concentration,
            "top10pct_cell_count": k,
        }
    return result


def detect_seed_replay(runs_for_condition: dict) -> dict:
    """条件内逐 seed 比对终末逐细胞向量（逐位相等判定重放重复）。"""
    seeds = sorted(runs_for_condition)
    vectors = {}
    for seed in seeds:
        cells = terminal_cells(load_run(runs_for_condition[seed]))
        vectors[seed] = [
            (cid, cells[cid]["phase"],
             tuple(repr(cells[cid][f]) for f in L2_FIELDS))
            for cid in sorted(cells)
        ]
    ref = vectors[seeds[0]]
    identical = all(vectors[s] == ref for s in seeds[1:])
    return {
        "seeds": seeds,
        "terminal_cell_vectors_identical_across_seeds": identical,
        "interpretation": (
            "seed 为重放重复，合并为单次确定性实现；统计推断只在细胞维度进行"
            if identical else
            "seed 间存在差异，逐 seed 结果需分别解释"
        ),
    }


# ---------------------------------------------------------------------------
# L4 交叉核对
# ---------------------------------------------------------------------------

def _effects_to_dict(effects) -> dict:
    if isinstance(effects, dict):
        return {k: float(v) for k, v in effects.items()}
    return {name: float(val) for name, val in effects}


def cross_check_l4(runs: dict, derived_summary_path: Path | None) -> dict:
    """从 raw 重算终末 L4 差值并与 derived/summary.json 比对。"""
    base_l4 = {
        seed: terminal_l4(load_run(path))
        for seed, path in sorted(runs[BASELINE_CONDITION].items())
    }
    recomputed = {}
    for cond in sorted(runs):
        if cond == BASELINE_CONDITION:
            continue
        for seed, path in sorted(runs[cond].items()):
            if seed not in base_l4:
                continue
            cond_l4 = terminal_l4(load_run(path))
            recomputed[f"{cond}|seed-{seed}"] = {
                m: cond_l4[m] - base_l4[seed][m] for m in L4_METRICS
            }

    report = {"recomputed_from_raw": recomputed, "derived_comparisons": []}
    if derived_summary_path is None or not derived_summary_path.exists():
        report["status"] = "derived/summary.json 不存在，跳过交叉核对"
        return report

    with derived_summary_path.open("r", encoding="utf-8") as fh:
        summary = json.load(fh)
    comparisons = summary.get("comparisons") or []
    n_match = 0
    n_checked = 0
    max_abs_discrepancy = 0.0
    for comp in comparisons:
        cond = comp.get("condition_id")
        if cond is None and "comparison_id" in comp:
            # empirical-l0 形式: "<condition>_vs_baseline"
            cond = comp["comparison_id"].rsplit("_vs_baseline", 1)[0]
        seed = comp.get("seed")
        derived_effects = _effects_to_dict(comp.get("final_metric_effects") or {})
        key = f"{cond}|seed-{seed}"
        rec = recomputed.get(key)
        entry = {"comparison_key": key, "metrics": {}}
        if rec is None:
            entry["status"] = "raw 中未找到对应配对，跳过"
            report["derived_comparisons"].append(entry)
            continue
        for m in L4_METRICS:
            if m not in derived_effects:
                continue
            diff = abs(rec[m] - derived_effects[m])
            max_abs_discrepancy = max(max_abs_discrepancy, diff)
            n_checked += 1
            ok = diff <= CROSS_CHECK_TOL
            n_match += int(ok)
            entry["metrics"][m] = {
                "recomputed": rec[m],
                "derived": derived_effects[m],
                "abs_discrepancy": diff,
                "match": ok,
            }
        report["derived_comparisons"].append(entry)
    report["status"] = "checked"
    report["n_metric_values_checked"] = n_checked
    report["n_metric_values_match"] = n_match
    report["max_abs_discrepancy"] = max_abs_discrepancy
    report["tolerance"] = CROSS_CHECK_TOL
    report["all_match"] = (n_checked == n_match)
    return report


# ---------------------------------------------------------------------------
# 单实验驱动
# ---------------------------------------------------------------------------

def analyze_experiment(name: str, raw_dir: Path, resamples: int) -> dict:
    runs = discover_runs(raw_dir)
    if BASELINE_CONDITION not in runs:
        raise SystemExit(f"{raw_dir} 缺少 baseline 条件")

    seed_audit = {
        cond: detect_seed_replay(runs[cond]) for cond in sorted(runs)
    }

    # 每个配对逐 seed 计算；随后核验 seed 间结果是否一致（重放重复判定）。
    pairings = []
    for cond in sorted(runs):
        if cond == BASELINE_CONDITION:
            continue
        seeds = sorted(set(runs[cond]) & set(runs[BASELINE_CONDITION]))
        per_seed = {}
        for seed in seeds:
            base_cells = terminal_cells(load_run(runs[BASELINE_CONDITION][seed]))
            cond_cells = terminal_cells(load_run(runs[cond][seed]))
            namespace = f"{name}|{cond}"
            per_seed[seed] = analyze_pair(
                base_cells, cond_cells, namespace, resamples)
        canonical_seed = seeds[0]
        canonical_json = json.dumps(per_seed[canonical_seed], sort_keys=True)
        seeds_identical = all(
            json.dumps(per_seed[s], sort_keys=True) == canonical_json
            for s in seeds[1:]
        )
        pairings.append({
            "condition": cond,
            "baseline": BASELINE_CONDITION,
            "seeds": seeds,
            "seed_results_byte_identical": seeds_identical,
            "canonical_seed": canonical_seed,
            "result": per_seed[canonical_seed],
        })

    derived_path = raw_dir.parent / "derived" / "summary.json"
    cross_check = cross_check_l4(runs, derived_path)

    return {
        "experiment": name,
        "raw_dir": str(raw_dir),
        "derived_summary": str(derived_path) if derived_path.exists() else None,
        "conditions": sorted(runs),
        "seed_audit": seed_audit,
        "pairings": pairings,
        "l4_cross_check": cross_check,
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def write_json(path: Path, obj) -> bytes:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    data = text.encode("utf-8")
    path.write_bytes(data)
    return data


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="M-GBA 效应稳健性探索性复分析（探索性诊断，不构成确认性结论）")
    parser.add_argument("--out", required=True, type=Path, help="输出目录")
    parser.add_argument("--experiment", required=True, action="append",
                        metavar="NAME=RAW_DIR",
                        help="实验名=artifact raw 目录，可重复")
    parser.add_argument("--bootstrap", type=int, default=10000,
                        help="bootstrap 重采样次数（默认 10000）")
    args = parser.parse_args(argv)

    experiments = []
    for spec in args.experiment:
        if "=" not in spec:
            parser.error(f"--experiment 需要 NAME=RAW_DIR 形式: {spec!r}")
        name, raw = spec.split("=", 1)
        raw_dir = Path(raw)
        if not raw_dir.is_dir():
            parser.error(f"raw 目录不存在: {raw_dir}")
        experiments.append((name, raw_dir))

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}  # relpath -> sha256
    details = []
    for name, raw_dir in experiments:
        detail = analyze_experiment(name, raw_dir, args.bootstrap)
        details.append(detail)
        fname = f"detail-{name}.json"
        data = write_json(out_dir / fname, {
            "schema_version": SCHEMA_VERSION,
            "exploratory_boundary": EXPLORATORY_DISCLAIMER,
            **detail,
        })
        written[fname] = sha256_hex(data)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "exploratory_boundary": EXPLORATORY_DISCLAIMER,
        "method": {
            "design": "同一 seed 下干预/消融条件 vs baseline 的逐细胞配对差值",
            "cell_alignment": "按 cell_id 取交集，非交集细胞如实记录",
            "l2_fields": list(L2_FIELDS),
            "l4_metrics": list(L4_METRICS),
            "bootstrap": (
                f"细胞级配对 bootstrap {args.bootstrap} 次重采样，95% 百分位 CI；"
                "随机流由 hashlib.sha256 对 "
                "(schema_version|experiment|condition|field|resample_index) "
                "派生，完全确定性，不使用 random 模块全局状态"
            ),
            "seed_policy": (
                "先做条件内 seed 逐位重复检测；确认为确定性重放重复后合并为单次"
                "确定性实现，统计推断只在细胞维度进行"
            ),
            "l4_cross_check": (
                "从 raw 重算终末 L4 指标相对 baseline 差值并与 derived/summary.json "
                "比对（容差 1e-9）；不一致时原样记录，不覆盖"
            ),
        },
        "experiments": [{
            "experiment": d["experiment"],
            "raw_dir": d["raw_dir"],
            "derived_summary": d["derived_summary"],
            "conditions": d["conditions"],
            "seed_audit": d["seed_audit"],
            "pairings": d["pairings"],
            "l4_cross_check": {
                k: v for k, v in d["l4_cross_check"].items()
                if k != "recomputed_from_raw"
            },
            "detail_file": f"detail-{d['experiment']}.json",
        } for d in details],
    }
    data = write_json(out_dir / "summary.json", summary)
    written["summary.json"] = sha256_hex(data)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "file_sha256": dict(sorted(written.items())),
    }
    write_json(out_dir / "manifest.json", manifest)

    print(f"已写出 {len(written) + 1} 个文件到 {out_dir}")
    for d in details:
        cc = d["l4_cross_check"]
        print(f"  {d['experiment']}: {len(d['pairings'])} 个配对, "
              f"交叉核对 {cc.get('n_metric_values_match')}/"
              f"{cc.get('n_metric_values_checked')} 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
