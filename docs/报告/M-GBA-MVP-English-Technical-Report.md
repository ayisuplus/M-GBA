# M-GBA 0.1.0 Technical Report

> Multi-scale Graph Biological Architecture  
> Version: 0.1.0  
> Date: 2026-08-18  
> Scientific status: deterministic, dimensionless cross-scale reference model

## Abstract

M-GBA investigates a bottom-up software architecture for digital-life research. Microscopic state does not directly set a macroscopic answer. Instead, state is transformed through five explicit runtime layers: regulatory dynamics (L0), coarse molecular dynamics (L1), cell state and action (L2), tissue graph and microenvironment dynamics (L3), and organism-level phenotype observation (L4). Multi-agent execution and semantic topology are treated as possible L2/L3 mechanisms, not as the definition of the project.

Version 0.1.0 implements a standard-library-only reference model with adjacent-layer contracts, deterministic multi-rate execution, exact JSON checkpoint resume, paired perturbation and ablation experiments, and a reporting pipeline rebuilt exclusively from raw trajectories. A frozen repair-expression knockdown propagates from L0 to a measurable L4 difference. Static replacement of L2 produces the largest endpoint change and changes all three deterministic runs from `FAILED` to `RECOVERED`, identifying the current five-state L2 accumulation rules as the leading diagnostic target. These are internal software-model results. They do not establish biological causality, clinical validity, or emergence.

## 1. Research questions

The 0.1.0 release asks:

1. Does every layer perform runtime computation without non-adjacent shortcuts in the primary generative path?
2. Can a controlled intervention applied only at L0 propagate through formal boundaries to L4?
3. Does replacing L1, L2, or L3 change the final phenotype enough to demonstrate that the layer is computational rather than decorative?

Real gene regulation, molecular structure, calibrated tissue biology, clinical repair prediction, and emergence are outside the evidence scope of this version.

## 2. Architecture

| Layer | Reference implementation | Accepted boundary | Output |
|---|---|---|---|
| L0 | Six-node deterministic discrete GRN | `Genome`, `RegulatoryInput`, previous L0 state | `TranscriptState` |
| L1 | Translation, degradation, receptor gating, inhibition | `TranscriptState`, `MolecularInput`, previous L1 state | `MolecularState` |
| L2 | Five-state cell machine | Same-cell L1 state, `LocalEnvironment`, previous L2 state | `CellState`, `CellAction` |
| L3 | Node stress/resource/signal dynamics on a fixed directed graph | Matched L2 states/actions and previous L3 state | `TissueState`, next local environments |
| L4 | Read-only phenotype observer and window classifier | `TissueState` | Five metrics and a frozen outcome |

The primary path is always `L0 -> L1 -> L2 -> L3 -> L4`. The persistent runner closes two adjacent fast feedback boundaries: L2-to-L1 local signaling and L3-to-L2 local environment. L4 remains observational. There is no L4-to-L3 downward control, so the current system is not a complete macro-to-micro feedback loop.

## 3. Execution and provenance

The `MultirateCrossScaleRunner` uses a dimensionless integer clock. L1, L2, and L3 update on every tick. L0 updates every five ticks and L4 observes every ten ticks, both anchored at tick 1. A tick stores formal layer states, inputs, actions, perturbation events, and adjacent transition events. A deterministic hash chain commits the ordered history.

An experiment manifest includes the scenario digest, layer model versions, runner version, and seed. Identical inputs produce the same experiment ID. Checkpoints contain the complete continuation state. A 13-tick run resumed for 87 ticks is exactly equivalent to a one-shot 100-tick run at the checkpoint, history digest, terminal observation, and phenotype-window levels.

## 4. Experimental protocol

The frozen WP8 matrix contains seven conditions, each run for 30 ticks with seeds 41, 42, and 43, for 21 raw runs:

- the five-layer `baseline`;
- repair expression clamped to 0.0, 0.5, or 1.0 at L0;
- static replacement of L1, L2, or L3, changing only the selected layer model version.

Every non-baseline record is paired with the same-seed baseline. L0-L4 effects are mean absolute distances in the current reference state spaces. Signed final differences are retained for vitality, damage burden, inflammation, homeostasis, and recovery capacity. These quantities are diagnostic software-model measures, not calibrated biological effect sizes.

## 5. Results

The frozen single-tick experiment ID is `mgba-023f543fb5a130ab`. The 100-tick baseline ID is `mgba-66654d1710f94556`, with history digest `7edbf3b897983ae4d24e1537bcc6b6d8850f3933adfeb6cc78b215c56d1350dc` and outcome `FAILED`. This negative baseline was retained without display-driven retuning.

The WP8 matrix ID is `matrix-7da4137aa39d5122`. Mean final L4 differences relative to the paired baseline are:

| Condition | Outcomes | Delta vitality | Delta damage | Delta homeostasis |
|---|---:|---:|---:|---:|
| `repair_kd_000` | 3 `FAILED` | -0.002460 | +0.002382 | -0.001464 |
| `repair_clamp_050` | 3 `FAILED` | +0.000439 | -0.000408 | +0.000259 |
| `repair_oe_100` | 3 `FAILED` | -0.000866 | +0.000798 | -0.000510 |
| `l1_static` | 3 `FAILED` | -0.013862 | +0.013302 | -0.008233 |
| `l2_static` | 3 `RECOVERED` | +0.469376 | -0.800620 | +0.581217 |
| `l3_static` | 3 `FAILED` | +0.010228 | -0.645599 | +0.101442 |

Complete repair knockdown has non-zero layer effects of approximately `0.034872 -> 0.028567 -> 0.001871 -> 0.000682 -> 0.001859` from L0 through L4. This demonstrates traceable attenuation through the implemented path. It does not imply that real biological propagation is instantaneous or follows these magnitudes.

The 0.5 clamp is deliberately not named a partial knockdown: whenever unconstrained expression would fall below 0.5, the clamp becomes an overexpression. The three clamps do not produce a simple monotonic L4 response under the current parameters. Static L2 replacement produces the largest endpoint effect, which diagnoses the baseline's state-transition and accumulation rules; it does not establish that a static cell model is biologically superior.

## 6. Raw-only reporting

WP9 reads the matrix manifest and all 21 raw runs. It never uses `derived/summary.json` as a reporting input. It reconstructs six condition summaries, 90 layer effects, 90 signed L4 metric effects, 630 L3 time-series rows, and 84 L4 observations. Outputs comprise five CSV files, four accessible SVG charts, one no-JavaScript static HTML report, and a SHA-256 report manifest.

The builder revalidates experiment identities, record coverage, tick continuity, history hash chains, and checkpoint identities. Corrupted raw identity or path escape fails closed. Deleting generated figures and rebuilding from the same raw inputs produces byte-identical files and hashes.

## 7. Reproducibility and quality gates

The project requires Python 3.11 or later and has no runtime dependencies outside the standard library. The release gate includes tests for adjacent contracts, model bounds and directional responses, local cell identity, fixed graph invariants, phenotype outcomes, multi-rate scheduling, exact checkpoint resume, the full causal matrix, raw-only report reconstruction, and the frozen demo flows.

The complete demonstration runs the single-tick trace, 100-tick trajectory, 21-run matrix, and report rebuild. The fallback demonstration is explicitly limited to the contract trace, a 30-tick runner trajectory, and the independent STEN smoke test. It is not evidence for WP8 or WP9.

## 8. Limitations

1. State, time, and effects are dimensionless and are not fitted to biological observations.
2. Dynamics are deterministic. Seeds 41, 42, and 43 produce identical numerical trajectories, so they are not independent statistical replicates.
3. L3 has a fixed directed topology and no geometry, mechanics, proliferation, movement, or calibrated diffusion.
4. L4 is observational and provides no macro-to-micro feedback.
5. No preregistered evidence currently supports population-dynamics or emergence claims.
6. STEN remains an independent L3 smoke subsystem outside the main five-layer run.
7. The results support software-architecture and within-model diagnostic claims only.

## 9. Conclusion

M-GBA 0.1.0 establishes a small but falsifiable vertical baseline. Its contribution is not the number of agents or model components; it is the executable separation of five scales, the prohibition of hidden layer shortcuts, and the ability to trace both positive and negative results to raw state transitions.

Future versions should first introduce justified stochastic processes, parameter sensitivity analysis, valid replication, and external calibration. L4 feedback, GNNs, dynamic topology, STEN, or LLM policies should then be introduced one layer at a time and compared against the frozen 0.1.0 rule-based baseline.

## Traceability

- Architecture: `docs/设计文件/架构设计.md`
- Causal protocol: `docs/决策记录/ADR-0008-WP8-扰动消融与因果路径.md`
- Reporting protocol: `docs/决策记录/ADR-0009-WP9-可重建报告与可视化.md`
- Experiment record: `docs/实验记录/WP8-reference-matrix-2026-08-18.md`
- Reproduction guide: `docs/复现/MVP-0.1.0-复现说明.md`
