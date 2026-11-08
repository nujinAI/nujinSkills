# Cynic Falsification Audit Specification

The Cynic Audit evaluates all quantitative trading strategies against **8 Canonical Gates** implemented in `core/cynic_gates.py` and `server/cynic_gates.py`.

## Core Standards
- **Maximum Drawdown Barrier (IS & Monte Carlo):** The 99th-percentile Monte Carlo simulated drawdown must not exceed 3.0\% (enforced by `MAX_MDD_99`).
- **Gate Matrix Verdicts:** Each gate evaluates to `PASS`, `FAIL`, or `INCONCLUSIVE`.
- **Single Source of Truth:** Gate evaluations are strictly computed by `cynic_gates.py` and rendered consistently across CLI and cockpit telemetry.
- **Detailed Protocol:** See [`references/cynic_gates_protocol.md`](cynic_gates_protocol.md) for full gate definitions and mathematical thresholds.
