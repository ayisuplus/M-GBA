# Changelog

All notable changes to M-GBA are documented here.

## Unreleased

### Added

- `mgba run-report` and `mgba.run_report.build_run_report`: rebuild a deterministic per-tick L0–L4 trajectory record (6 SVG charts, 6 CSVs, read-only HTML, SHA-256 manifest) from any saved run artifact (`simulate --trace-out` or a matrix raw run).
- Run artifacts are validated fail-closed before charting: experiment manifest, history hash chain, and checkpoint identity are recomputed from raw ticks; tampered or checkpoint-resumed partial artifacts are rejected.
- Optional L4→L3 homeostatic feedback loop (ADR-0012): a deterministic discrete PI controller with dead-zone, back-calculation anti-windup, and a memoryless safety-barrier stress floor (`mgba.feedback.HomeostaticFeedbackController`, `FixedConstraintPolicy`), feeding an audited `FeedbackConstraint` into a new `ConstraintAwareTissueModel`. The controller is opt-in (`MultirateCrossScaleRunner(..., feedback_policy=...)`); checkpoint state is rebuilt by deterministic replay of stored L4 observations, so the checkpoint schema is unchanged.
- `mgba feedback-experiment` CLI and `mgba.feedback_experiments`: the frozen E4 protocol comparing no-feedback, fixed-feedback, and state-feedback conditions with the WP8 paired-comparison metrics, plus raw/derived artifact persistence.
- `scripts/synthetic_feedback_benchmark.py`: seeded synthetic scenario dataset generator (4 stress regimes, heterogeneous abstract genomes, ring+chord topologies) and an E4 benchmark runner producing CSV + JSON summaries; regeneration is idempotent and conflict-refusing.
- `tests/test_feedback.py` (23 tests): extreme edge cases — NaN/inf/out-of-range config fail-fast, dead-zone, integrator windup clamp, actuator saturation, time regression, malformed policy/constraint rejection, monotone safety barrier, byte-equivalence without constraint, checkpoint-replay determinism.
- `tests/test_frozen_identity.py`: regression gate pinning the single-tick, 100-tick, and WP8 matrix identities against drift.
- Active-inference (free-energy) L2 policy (ADR-0013): `mgba.layers.l2_active_inference.ActiveInferenceCellModel` selects the cell phase by minimizing Expected Free Energy (risk + ambiguity decomposition, deterministic argmin, no sampling) over five candidate actions with a frozen interoceptive generative model; it reuses the rule model's drive semantics and state bookkeeping so a policy swap isolates only the decision rule. The rule state machine is untouched and stays the default.
- `mgba policy-experiment` CLI and `mgba.policy_experiments`: paired rule-vs-active-inference L2 policy matrix reusing WP8 paired comparisons; the runner constructor enforces that the inference runner differs from the rule runner in L2 only.
- `scripts/synthetic_policy_benchmark.py`: runs the rule-vs-AIF matrix over the synthetic dataset (shared generator with the feedback benchmark) and aggregates CSV + JSON summaries.
- `tests/test_active_inference.py` (18 tests): numerical extremes (degenerate drives, sharp/flat beliefs, saturated failure probabilities), config fail-fast, dead absorbing state, determinism, contract violations, and paired-matrix invariants (L0 effect exactly zero; L1 effect bounded by adjacent L2→L1 feedback).
- Dynamic L3 topology governance (ADR-0014): `mgba.layers.l3_adaptive.DynamicTopologyTissueModel` implements stress-avoidance T1-style edge swaps under a proposal→authorization→commit loop (cells propose intent from local information; the system authorizes via self-loop/duplicate/dead-node/degree-cap/marginal-gain constraints and enforces a per-tick swap budget). Topology state lives in `TissueState.edges`; every committed swap is serialized into the L3 source-digest hash chain. `_validated_inputs` gains a `dynamic_topology=False` flag so the static trajectory gate is unchanged by default.
- `mgba topology-experiment` CLI and `mgba.topology_experiments`: the frozen E5 protocol comparing static vs adaptive topology with WP8 paired metrics plus E5 topology-stability metrics (committed swaps, swap ticks, edge-count delta); the runner constructor enforces that the adaptive runner differs in L3 only.
- `scripts/synthetic_topology_benchmark.py`: runs the E5 matrix over the shared synthetic dataset and emits results + topology-stability CSVs and a JSON summary.
- `tests/test_topology.py` (15 tests): config fail-fast, single-cell tissue, zero/one swap budgets, edge-count and in-degree conservation under T1 exchanges, degree-cap enforcement, determinism, audit-chain divergence, static-condition byte identity, and matrix invariants.
- Seeded stochastic transcriptional noise at L0 (ADR-0015): `mgba.layers.l0_noisy.NoisyDiscreteGrnModel` keeps the deterministic leaky-update right-hand side bit-for-bit and adds bounded multiplicative noise per gene via a noise stream derived from `sha256(seed|cell|time)` — stateless, checkpoint-exact, and audited through the L0 source-digest chain. Zero-sigma reproduces deterministic gene values exactly.
- `mgba.e3_statistics` + `mgba.e3_experiments` + `mgba e3-experiment`: the W14/M9 E3 population protocol — multi-seed noisy-L0 ensembles graded by pre-registered criteria (CV stability, OLS micro-drive decoupling, persistence) into the AGENTS.md terminology ladder (`insufficient_seeds` / `no_pattern` / `emergence_candidate` / `group_dynamics` / `aggregation`); no p-values are claimed.
- `scripts/synthetic_e3_benchmark.py`: runs the E3 ensemble over the shared synthetic dataset and emits grade counts, per-metric statistics CSV, and a JSON summary.
- `tests/test_e3_statistics.py` (16 tests): noise determinism, bounded values under sigma=1.0, exact perturbation clamps, zero-sigma equivalence, checkpoint replay under noise, config fail-fast, all five E3 grades reachable, OLS degeneracy, ensemble determinism, and the frozen 100-tick baseline guard.
- Stochastic closed-loop feedback-under-noise matrix (ADR-0016): `mgba.closed_loop_experiments` + `mgba closed-loop-experiment` combine the ADR-0012 homeostatic controller with the ADR-0015 seeded noise in a three-condition matrix (stochastic open loop, stochastic closed loop, deterministic closed loop), grading each run's scheduled homeostasis series through a pre-registered stability ladder (insufficient_observations / oscillation / lock / recovery / deterioration / indeterminate) computed from first-difference sign changes, amplitude, and trend.
- `scripts/synthetic_closed_loop_benchmark.py`: runs the closed-loop matrix over the shared synthetic dataset and emits stability-grade CSV + JSON summary.
- `tests/test_closed_loop.py` (11 tests): all six stability grades on hand-built sequences, threshold exclusivity, config fail-fast, out-of-range grade DTO rejection, matrix determinism under noise, trajectory identity of deterministic conditions, and the frozen 100-tick baseline guard.
- The default report output refuses locations inside a raw artifact directory; pass `--output-dir` explicitly for matrix raw runs.
- Heterogeneous per-layer neural contract demonstrators (ADR-0017): `mgba.neural` pure-stdlib primitives (sha256-seeded `seeded_matrix` with Xavier-style fan-in bound, overflow-safe `mlp_forward`, mean-aggregator `message_passing_step`) plus two opt-in frozen-weight layer variants — `mgba.layers.l0_neural.NeuralGrnModel` (13→hidden tanh→6 sigmoid MLP with reference leaky update and exact post-hoc perturbation clamps) and `mgba.layers.l3_gnn.GnnTissueModel` (one-hop message passing over the static graph, frozen ADR-0005 damage aggregation, constraints rejected like the reference model). Weights are derived from explicit seeds, never trained; the rule reference models stay default and permanent baselines.
- `mgba neural-experiment` CLI and `mgba.neural_experiments`: paired reference-vs-neural single-layer swap matrix (`--layer l0|l3`) reusing WP8 paired comparisons; the runner constructor enforces that the two runners differ in exactly the swapped layer.
- `scripts/synthetic_neural_benchmark.py`: runs both L0 and L3 swap matrices over the shared synthetic dataset and emits per-condition final-L4 CSV + JSON summaries with per-layer effects.
- `tests/test_neural.py` (22 tests): kernel determinism/fail-fast/saturation safety, L0/L3 variant protocol conformance and determinism, exact perturbation clamps after the MLP, static-topology gate inheritance, single-cell and all-dead tissues, single-layer-swap enforcement, budget rejection, and the frozen 100-tick baseline guard.

### Scientific boundary

- Feedback is a downward constraint channel only: it reshapes L3 resource ceiling / stress floor at the L4 slow clock, never prescribes L2 actions, and every constraint enters the L3 source-digest hash chain for auditability.
- E4 reference conditions currently end `FAILED` in all synthetic regimes under the unfitted reference parameters; these are retained as negative baselines, not tuned for display.
- The active-inference policy is a reference-model experiment, not a claim that free-energy minimization is biologically validated; under unfitted parameters all policy conditions still end `FAILED` in every synthetic regime, retained as negative baselines.
- Charts show dimensionless reference-model proxies; L0–L3 series are per-tick means across cells, and L4 is charted only at scheduled slow-clock observations.
- Dynamic topology is an E5 reference comparison, not a validated self-organization result: under frozen governance thresholds the default scenario commits zero swaps and all synthetic regimes still end `FAILED`; negative baselines retained without tuning.

- E3 grading implements — and deliberately stops short of — validated results: an `emergence_candidate` grade under unfitted parameters means the pre-registered criteria were met, not that emergence is proven; frozen-protocol statistics and layer ablations remain future work per AGENTS.md §4.
- Stability grading is a reference-model diagnostic only: under unfitted controller parameters, all closed-loop conditions currently grade `deterioration`/`lock`/`indeterminate` with no `recovery`, an honest negative baseline for the E4 feedback question.
- The neural layer variants are frozen-weight contract demonstrators, not trained models: the repository holds no supervision targets or training data, so the MLP/GNN weights are derived deterministically from explicit seeds and quantify only the trajectory impact of a layer swap — no neural-fidelity, training-capability, or compute-savings claims are made.

## 0.2.0 - 2026-08-19

### Added

- A TCGA-proxy-anchored CAR-M scenario package compiled into the unchanged L0–L4 contracts.
- De-identified cohort aggregation with source SHA-256 provenance and explicit proxy-label boundaries.
- Deterministic CAR-M Cell and fixed tumor-microenvironment models for L2 and L3.
- Backward-compatible group perturbations and a frozen 21-run CAR signal dose/ablation matrix.
- `carm-import` and `carm-experiment` commands, CAR-M provenance artifacts, tests, and documentation.

### Scientific boundary

- The CAR-M slice is a mechanism-informed reference model, not a calibrated biological or clinical predictor.
- The legacy patient-level GAT is not used in the generative hot path.
- The frozen high-dose result increases inflammation and slightly increases the final burden proxy; it is retained as a negative baseline.
- Spatial ABM behavior, stochastic replication, model retraining, dynamic topology, and the React UI remain deferred.

### Reference identity note

- `code_version` moved to `0.2.0`, so manifest-derived run identities moved honestly: single-tick `mgba-3a179a5a3c399f6d`, 100-tick `mgba-06a3c6124501f1d6`, history digest `4b008f6ca8fa481df1025683f16f306cc3a44505ddff359131e09167ed3920a2`.
- Layer dynamics did not move: the single-tick trace digest is still `20f9578497fd67d04071cd4cd08627262ff883a620d5c7c02ea7dff4014a0135`, the 100-tick outcome is still `FAILED`, and the WP8 matrix is still `matrix-7da4137aa39d5122`.
- The `m-gba==0.1.0` identities remain recorded in the 0.1.0 release documents and still reproduce from the 0.1.0 wheel.

## 0.1.0 - 2026-08-19

### Added

- Five adjacent runtime layers from an abstract discrete GRN (L0) to organism-level phenotype observation (L4).
- Deterministic multi-rate execution, trace hash chains, JSON checkpoints, and exact resume.
- Paired L0 perturbations and L1–L3 static-model ablations over a frozen 21-run causal matrix.
- Raw-only rebuilding of CSV tables, accessible SVG charts, a static HTML report, and SHA-256 file manifests.
- Frozen full and fallback demonstration flows.
- Chinese design report, English technical report, reproduction guide, and release checklist.

### Scientific boundary

- The implementation is a dimensionless deterministic reference model, not a calibrated biological simulator.
- Seed replicates currently have identical trajectories; no statistical significance or emergence claim is made.
- Dynamic topology, L4 downward feedback, valid stochastic replication, GNNs, and LLM policies remain future work.
