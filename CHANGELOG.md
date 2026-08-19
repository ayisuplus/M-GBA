# Changelog

All notable changes to M-GBA are documented here.

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
