# Contributing to nujinSkills

Thank you for your interest in contributing to **nujinSkills**! This project is built to put institutional-grade, autonomous quantitative research and systematic execution in everyone's hands—free, open-source, and 100% on CPU.

Every contributor whose pull request is merged is **attributed in [`README.md`](README.md#contributing--contributors)**.

---

## Ways to Contribute

- **Quantitative Research & Falsification Tools (`core/`, `tools/`):** New causal indicators, market-structure primitives, statistical tests, or performance improvements.
- **Agent Skill & Protocols (`SKILL.md`, `references/`):** Clarifying agent instructions, improving research protocols, or documenting new workflows.
- **Bug Reports & Feature Requests:** Reproducible issues, edge-case reports, or well-reasoned proposals.
- **Tests & Documentation:** Expanding test coverage (`tests/`) and keeping docs accurate.

---

## Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/nujinSkills.git
   cd nujinSkills
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Run the test suite:**
   ```bash
   pytest
   ```

---

## Engineering & Quantitative Standards

To preserve the mathematical and operational rigor of `nujinSkills`, please follow these standards:

1. **Strict Causality (Zero Lookahead):** Any indicator, feature, or market-structure logic must be strictly causal and prefix-invariant. Never leak future bar data into historical signals.
2. **No Silent Fallbacks or Hardcoded Capital:** Fail explicitly on missing/corrupt data or invalid parameters. Risk and position sizing must remain dynamic.
3. **CPU-First Performance:** Keep research, scanning, and validation tools fast and runnable on standard CPU hardware without requiring a GPU.
4. **Focused, Tested Changes:** Keep pull requests scoped to a single concern. Add or update unit tests in `tests/` for bug fixes and new features.
5. **Keep Docs in Sync:** If your change alters CLI flags, protocols, or agent behavior, update the corresponding files (`SKILL.md`, `references/`, or `README.md`).

---

## Pull Request Process

1. Create a branch from `main` with a descriptive name (e.g., `feat/add-indicator`, `fix/causal-resample`, `docs/update-cynic-gates`).
2. Make your changes and ensure `pytest` passes locally.
3. Open a Pull Request against `main` with:
   - A clear summary of **what** changed and **why**.
   - How you tested/verified the change.
   - Any relevant issue links.

---

## Contributor Attribution

We believe in recognizing everyone who helps build `nujinSkills`.

- All merged contributors are credited in the **Contributors** section of [`README.md`](README.md#contributing--contributors).
- You may either add your name/GitHub handle and contribution summary to the Contributors list in `README.md` as part of your PR, or maintainers will add you upon merge.
