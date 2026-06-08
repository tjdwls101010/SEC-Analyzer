# Decisions

Newest first. Each entry: `## YYYY-MM-DD — short title`, then 1–3 sentences (context + decision + why).

## 2026-06-08 — 0.2.0 plan: adversarial-review open questions resolved

From the multi-agent issue review: (1) XBRL geographic-leak filter uses the robust "member also on the geographic axis in the same filing" rule, not the brittle keyword denylist; (2) the inventory `pct_of_total` period-selection bug is fixed (most-recent `period_instant` denominator, not `iloc[0]`); (3) provider refusals are non-retryable (surface the reason immediately); (4) the library return stays python-mode `model_dump()`; (5) CI wiring ships with placeholder tests so it is demoable before the test slices land. Recorded so the implementing session does not reopen them.

## 2026-06-08 — Custom-Preset `.format()` brace bug gets its own slice

The prompt builder's `str.format()` raises `KeyError` on a literal `{` in a custom Preset's field description or `__prompt__` (the advertised custom-Preset feature, PRD stories 5/6). Rather than expand the OpenRouter-migration scope, it is fixed as a separate slice (brace-safe substitution of only `{company_name}`/`{filing_text}`), blocked by the migration slice since both touch the prompt path.

## 2026-06-08 — PyPI release triggers on GitHub Release published (not tag push)

The publish workflow fires on `release: published` (+ `workflow_dispatch`) only; pushing a bare `vX.Y.Z` tag does not publish. Chosen over tag-push triggering because an explicit, reversible Release gesture (with release notes) suits a non-developer maintainer and avoids accidental premature publishes.

## 2026-06-07 — Default model: deepseek/deepseek-v4-flash, reasoning off

Benchmarked flash across reasoning effort (`none`→`xhigh`) and flash/none vs pro/none on **10 diverse tickers** — see `docs/benchmark-model-selection.md`, the authoritative record. flash/none: 10/10 success, ~35 s, ~$0.02/filing, 5.1 avg fields. pro/none: only 6/10 (failed NVDA, AAPL on JSON truncation; CAT, ASML by emitting field `name` instead of `entity`), ~18× cost, slower, quality tied — not dramatically better, so it loses the balanced + on-demand criterion. Reasoning ON reliably *hurt*: no quality gain, latency up to ~104 s at `xhigh`, and broken structured output (empty `content=None` / markdown-not-JSON / truncation). So reasoning is `none` by default (sends no reasoning field on the wire), raisable via `OPENROUTER_REASONING_EFFORT`; pro remains opt-in via `OPENROUTER_MODEL`. These failure modes are engineering requirements: handle `content=None` (retry, never validate None), surface the real provider error, keep retries.

## 2026-06-07 — Weekly live health-check in CI

The project broke silently when edgartools major-bumped (3.x→5.x) and the Gemini billing lapsed — undetected until a manual review. A scheduled weekly CI job now runs a real SEC + OpenRouter extraction so future external drift is caught automatically; per-push CI stays offline-only (mocked) to avoid cost and flakiness.

## 2026-06-07 — Pin dependency upper bounds

Unbounded `>=` requirements let edgartools drift from 3.x to 5.x and silently break XBRL extraction. Dependencies now carry upper bounds (e.g. `edgartools>=5,<6`), so a major bump becomes an explicit, reviewed upgrade rather than a surprise.

## 2026-06-07 — Publish workflow named `workflow.yml` for Trusted Publishing

PyPI's Trusted Publisher for this project is registered against a workflow file named `workflow.yml`. The publishing workflow is therefore `.github/workflows/workflow.yml` (renamed from `publish.yml`) so OIDC matches without the maintainer re-touching PyPI.

## 2026-06-07 — Tag-driven versioning via hatch-vcs

Release version is derived from the git tag (hatch-vcs) instead of a hardcoded `version` in `pyproject.toml`, so a GitHub release `vX.Y.Z` becomes the PyPI version automatically — no manual bump, no version/tag mismatch.

## 2026-06-07 — Next release is 0.2.0, clean break (drop `GOOGLE_*` env vars)

Migrating the LLM backend changes config from `GOOGLE_API_KEY`/`GOOGLE_MODEL` to `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`, which is incompatible with 0.1.0. Since 0.1.0 is alpha with effectively no users, we ship 0.2.0 with no backward-compat shims rather than carry dual-variable complexity.

## 2026-06-07 — Keep and fix XBRL extraction on edgartools 5.x

`extract_xbrl()` broke because edgartools 5.x removed `xbrl.instance` (data now reached via `xbrl.facts.to_dataframe()` with renamed columns). Rather than drop the feature, we rewrite it for the 5.x FactsView API, because XBRL gives quantitative ground-truth that complements and cross-checks the LLM extraction.

## 2026-06-07 — Replace Gemini with OpenRouter as the only LLM backend

The LLM backend moves from google-genai (Gemini) to OpenRouter's OpenAI-compatible API, model selectable via `OPENROUTER_MODEL`. We do **not** keep a multi-provider abstraction: OpenRouter already exposes hundreds of models behind one seam, so a second provider adapter would add test and maintenance cost for no current variation (one adapter = hypothetical seam).
