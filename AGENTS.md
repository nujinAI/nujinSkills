# Agent Guidelines: NujinSkills

## Two Scopes
- **Quant Research / Strategy Work:** Treat `core/`, `tools/`, `server/`, `frontend/`, and `tests/` as a black box—never read or edit them. Follow [`SKILL.md`](SKILL.md) and [`references/api_cheatsheet.md`](references/api_cheatsheet.md).
- **Engine / Repository Development:** Obey the 5 Non-Negotiable System Laws below.

## 5 Non-Negotiable Open-Source System Laws
1. **Universal & Dynamic Only:** Never hardcode symbol-, timeframe-, asset-class-, or user-specific branches or personal trading artifacts.
2. **Zero Silent Fallbacks & Zero Hardcoded Capital:** Fail loudly with actionable errors on missing/corrupt data or invalid parameters; never silently return defaults.
3. **Zero Mock / Placeholder Data in Production:** Mocks and synthetic fixtures belong strictly in `tests/`.
4. **Single Source of Truth (`core/`) & Strict Causality:** All quantitative math, risk sizing, simulation, and audit logic lives in `core/` (never duplicated in `tools/` or `server/`), and must be strictly prefix-invariant (zero lookahead).
5. **Ask Before Assuming:** If a requirement, edge case, or architectural tradeoff is ambiguous, ask the user before implementing—never guess or add silent workarounds.

## Definition of Done (Engine Changes)
Add or update regression test(s) in `tests/`, sync [`SKILL.md`](SKILL.md) / [`references/api_cheatsheet.md`](references/api_cheatsheet.md) if any CLI flag or schema changed, and verify with `.venv/bin/python -m pytest` and `.venv/bin/python -m tools.preflight`.
