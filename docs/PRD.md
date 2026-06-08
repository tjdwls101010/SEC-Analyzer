# PRD — SEC-Analyzer revival (OpenRouter migration + edgartools 5.x + release automation)

## Problem Statement

SEC-Analyzer (v0.1.0, published to PyPI 2026-03-23) silently stopped working:

- **The LLM backend is dead.** The Gemini API key expired, and even with a fresh key the Google AI project's prepayment credits are depleted — so every `extract()` fails. The failure is also *hidden*: the code reports a generic `"LLM extraction failed"` instead of the real cause.
- **XBRL extraction is broken.** edgartools drifted from the pinned-floor `>=3.0` to `5.35.1`; `xbrl.instance` was removed, so `extract_xbrl()` raises `AttributeError`.
- **A fresh install is broken too.** `engine.py` imports `pandas`, but `pandas` is not declared as a dependency — `pip install sec-analyzer` then `extract_xbrl()` → `ImportError`.
- **Nobody noticed.** There is no automated check, so the PM only found out by manually auditing months later.
- **Releasing is manual and fragile.** The published version is hardcoded; a GitHub release does not flow to PyPI.

The maintainer is a non-developer PM who needs the tool to (a) work again, (b) tell *itself* when it breaks, and (c) release with one action.

## Solution

Revive and harden the library:

1. **Migrate the LLM backend to OpenRouter** (OpenAI-compatible), model chosen via `.env`. One provider, hundreds of models. Default model chosen by empirical benchmark.
2. **Fix `extract_xbrl()`** for the edgartools 5.x `FactsView` API, keeping the four quantitative categories.
3. **Make the install honest** — declare every runtime dependency (add `openai`, `pandas`; drop `google-genai`) and **pin upper bounds** so a major upstream bump is an explicit upgrade, never a silent break.
4. **Surface real errors** — a failed extraction reports the underlying provider cause (depleted credits, unknown model, rate limit).
5. **Self-monitoring** — offline tests on every push (free, fast); a **weekly live health-check** in CI that performs a real extraction and fails loudly when an external dependency drifts.
6. **One-action releases** — a GitHub release `vX.Y.Z` auto-publishes that version to PyPI via OIDC Trusted Publishing, version derived from the tag.

Shipped as **0.2.0**, a clean break (no `GOOGLE_*` backward compat).

## User Stories

**LLM extraction**

1. As an analyst, I want to extract structured data from a ticker's latest 10-K so I get suppliers/customers/etc. as JSON without reading the filing.
2. As an analyst, I want foreign issuers with no 10-K to auto-fallback to 20-F so I don't need to know the form type.
3. As an analyst, I want to pass an explicit `form` (10-Q, 20-F, DEF 14A) so I can target a specific document.
4. As an analyst, I want to pass a `filing_date` so I can extract from a historical filing instead of the latest.
5. As a developer, I want to define my own **Preset** (Pydantic model) so I can extract any schema I need, not just supply chain.
6. As a developer, I want an optional `__prompt__` on my Preset so I can steer how the model extracts.
7. As an AI agent, I want `extract()` to return a stable `{"filing": …, "data": …}` shape so I can consume it programmatically.
8. As a user, I want to pick the **Model** via `OPENROUTER_MODEL` (or a `model=` argument) so I can trade off speed, quality, and cost.
9. As a user, I want a sensible default model so the tool works out of the box with zero model config.
10. As a user, I want my key read from `OPENROUTER_API_KEY` (env or `.env`) so I never hardcode a secret.
11. As a user, when extraction fails I want the **real reason** (missing key, depleted credits, unknown model, rate limit) — not a generic "failed" — so I know exactly what to fix.
12. As a user, I want transient provider/network failures retried with backoff so a brief blip doesn't fail my run.

**CLI**

13. As a CLI user, I want `sec-analyzer NVDA --preset supply-chain` to print JSON so I can use it from a shell or script.
14. As a CLI user, I want `--preset module:ClassName` so I can use my own Preset from the CLI.
15. As a CLI user, I want `--json` compact output so I can pipe it cleanly; and the CLI should exit non-zero with a readable error on failure.

**XBRL (quantitative ground-truth)**

16. As an analyst, I want `extract_xbrl()` to return quantitative facts (revenue concentration, geographic revenue, inventory composition, purchase obligations) pulled straight from XBRL tags, with **no LLM**.
17. As an analyst, I want `extract_xbrl()` to report `xbrl_available: false` when a filing has no usable XBRL, rather than crash.
18. As an analyst, I want to cross-check LLM-extracted numbers against the XBRL ground-truth.

**Install & docs**

19. As a new user, I want `pip install sec-analyzer` to pull everything it needs (incl. pandas) so no feature ImportErrors at runtime.
20. As a new user, I want the README quickstart to reflect OpenRouter so the documented setup actually works.

**Reliability & release (revival drivers)**

21. As the maintainer, I want dependency **upper bounds** so a major upstream release can't silently break the library again.
22. As the maintainer, I want a **weekly automated live health-check** so I'm alerted the moment SEC/edgartools/OpenRouter drift breaks extraction.
23. As the maintainer, I want **offline unit tests on every push** so logic regressions are caught fast and for free.
24. As the maintainer, I want a **GitHub release to auto-publish to PyPI** (OIDC, no token), version derived from the tag, so releasing is a single action.

## Implementation Decisions

**Modules / interfaces** (domain language from `CONTEXT.md`):

- `extract(symbol, preset, form="10-K", filing_date=None, max_chars=…, api_key=None, model=None) -> dict` — interface unchanged; `api_key`/`model` now refer to OpenRouter.
- `extract_xbrl(symbol, form="10-K") -> dict` — unchanged interface; reimplemented on edgartools 5.x.
- `_extract_with_llm(...)` — reimplemented against OpenRouter (the **Provider**).

**LLM Provider (OpenRouter):**
- Use the `openai` SDK with `base_url=https://openrouter.ai/api/v1` (override via `OPENROUTER_BASE_URL`).
- **Structured output:** `response_format={"type":"json_schema","json_schema":{"name":<preset>,"strict":True,"schema":preset.model_json_schema()}}`. The **raw** Pydantic schema (with `$defs`/`$ref`) works with `strict:true` — no strictify step needed (verified empirically; strictify only added wasted reasoning tokens).
- **Default model:** `deepseek/deepseek-v4-flash` (confirmed by benchmark: flash/none 10/10 vs pro/none 6/10 — pro failed NVDA/AAPL on JSON truncation and CAT/ASML by emitting field `name` instead of `entity` — at ~18× the cost and tied quality; see `docs/benchmark-model-selection.md`). `deepseek/deepseek-v4-pro` stays available via `OPENROUTER_MODEL`. Override per-call via `model=`.
- **Reasoning:** off (`none`) by default; configurable via `OPENROUTER_REASONING_EFFORT` (`none`/`minimal`/`low`/`medium`/`high`/`xhigh`; `none` sends no reasoning field on the wire). An effort sweep showed no reliable quality gain, latency up to ~104 s/filing at `xhigh`, and broken structured output (empty content / markdown-not-JSON / truncation) — so off is the default.
- `temperature=0` for determinism.
- **Error surfacing:** raise `ValueError` if no key; on exhausted retries raise `RuntimeError` that **includes the underlying provider error string**.
- **Empty content:** if the provider returns `content is None` (observed with reasoning on / refusals), treat it as a failed attempt and retry — never call `model_validate_json(None)`.
- Retries: 3 with exponential backoff.

**Config / env:** `OPENROUTER_API_KEY` (required), `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` (optional), `OPENROUTER_REASONING_EFFORT` (optional), `EDGAR_IDENTITY` (optional, has fallback). Loaded via `python-dotenv`.

**XBRL on edgartools 5.x:** reach facts via `filing.xbrl().facts.to_dataframe()` (a `FactsView`). New columns: `concept`, `value`/`numeric_value`, `period_type`, `period_start`, **`period_end`** (was `end_date`), `dimension`, `member`, and `dim_<ns>_<Axis>` dimension columns (prefix `dim_`, underscores not colons). Re-map the four category extractors onto these. Keep graceful `xbrl_available: false` on any failure.

**Dependencies (pinned):** `openai>=2,<3`, `edgartools>=5,<6`, `pydantic>=2,<3`, `python-dotenv>=1,<2`, `pandas>=2,<4`; **remove** `google-genai`. (Exact bounds finalized against resolved versions.)

**Packaging / versioning:** hatch-vcs derives `version` from the git tag; `pyproject.toml` `version` becomes dynamic. No hardcoded version to drift.

**CI / release:**
- `.github/workflows/workflow.yml` (named to match the existing PyPI Trusted Publisher): on `release: published` → build → publish via OIDC (`id-token: write`, no password/token). Keep `workflow_dispatch` for manual runs.
- Offline test workflow on push/PR.
- Weekly scheduled (`cron`) + manual live health-check workflow using the `OPENROUTER_API_KEY` repo secret.

## Testing Decisions

- **Mock only at system boundaries** (the OpenRouter **Provider**, and SEC/edgartools). Never mock internal collaborators. Tests describe behavior through the public interface (`extract`, `extract_xbrl`, CLI), surviving refactors.
- **Offline suite (every push, in CI):**
  - Preset schema is valid and round-trips (`model_json_schema` → `model_validate_json`).
  - `_extract_with_llm` builds the right `response_format` and parses a mocked OpenRouter reply into the Preset.
  - **Error surfacing:** a mocked provider error (e.g. depleted-credits) propagates its message through `RuntimeError` (regression test for the swallowed-error bug).
  - **Empty content:** a mocked `content=None` reply is retried and never passed to `model_validate_json`; after exhausted retries the `RuntimeError` is specific (names the model + attempt count). This is the key benchmark-derived failure mode (reasoning-on empty responses).
  - Missing key → `ValueError`.
  - CLI: `module:ClassName` loads; unknown preset exits non-zero with a helpful message.
  - XBRL: a small **recorded** facts DataFrame fixture → correct category mapping (incl. `period_end` column), and empty/missing XBRL → `xbrl_available: false`.
- **Live suite (weekly schedule + manual dispatch):** real `extract("NVDA", SupplyChain)` and `extract_xbrl("NVDA")` assert a well-formed, non-empty result. Marked (e.g. `@pytest.mark.live`) and excluded from the per-push run.
- **Prior art:** `tests/benchmark.py` is a *manual* quality/perf tool (needs key, network, money) — kept as a tool, not part of the automated suite.

## Out of Scope

- Multi-provider abstraction — OpenRouter only (it already provides model choice).
- Backward compatibility with `GOOGLE_*` env vars.
- New Presets beyond `SupplyChain`.
- Streaming output, async API, caching of filings/extractions.
- Any UI/web surface.
- Raising the model's truncation limit / chunking very large filings (the `max_chars` cap stays; revisit only if benchmark shows truncation hurting quality).
