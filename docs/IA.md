# IA — SEC-Analyzer

PRD answers WHY/WHAT; this answers *how the user experiences it*. SEC-Analyzer has no screens — its "surfaces" are the **install flow, environment config, the Python API, the CLI, and the result/error shapes**. This maps those touchpoints and the paths through them.

## Touchpoint tree

```
SEC-Analyzer
├── Install            pip install sec-analyzer        (pulls openai, edgartools, pydantic, pandas, dotenv)
├── Configure (.env / env vars)
│   ├── OPENROUTER_API_KEY     (required)
│   ├── OPENROUTER_MODEL       (optional → default deepseek/deepseek-v4-flash)
│   ├── OPENROUTER_REASONING_EFFORT (optional → none)
│   ├── OPENROUTER_BASE_URL    (optional)
│   └── EDGAR_IDENTITY         (optional → fallback)
├── Python API
│   ├── extract(symbol, preset, …)        → {"filing": {...}, "data": {...}}
│   ├── extract_xbrl(symbol, form)        → {"filing": {...}, "data": {...}, "xbrl_available": bool}
│   └── presets.SupplyChain               (built-in Preset; or user module:ClassName)
└── CLI: sec-analyzer
    ├── sec-analyzer NVDA                       (default preset = supply-chain)
    ├── sec-analyzer TSM --form 20-F
    ├── sec-analyzer AAPL --filing-date YYYY-MM-DD
    ├── sec-analyzer NVDA --preset my_pkg.presets:MyPreset
    └── --json                                  (compact output)
```

## Primary path — "extract a filing"

1. **Install** → `pip install sec-analyzer`.
2. **Configure** → set `OPENROUTER_API_KEY` (in a `.env` or the environment). Nothing else is required.
3. **Call** → `extract("NVDA", preset=SupplyChain)` (or the CLI equivalent).
4. **Under the hood** (invisible to the user): load latest 10-K via edgartools → markdown → send markdown + Preset schema to the Model via OpenRouter (strict structured output) → validate reply into the Preset.
5. **Receive** → `{"filing": {form, filing_date, accession_number, filing_url}, "data": {<preset fields>}}`.

## Result hierarchy (what the user reads first)

- **`filing`** — provenance, always present: which document the data came from (`form`, `filing_date`, `accession_number`, `filing_url`). Lets the user trust/verify.
- **`data`** — the Preset's fields. For `SupplyChain`: suppliers, customers, single_source_dependencies, geographic_concentration, capacity_constraints, supply_chain_risks, revenue_concentration, geographic_revenue, purchase_obligations, market_risk_disclosures, inventory_composition. Empty fields are present as empty lists (predictable shape for an agent).
- **`xbrl_available`** (XBRL path only) — `true`/`false` up front, so the consumer branches cleanly when a filing has no usable XBRL.

## Error experience (must be legible — this is a revival driver)

- **No key** → `ValueError` naming `OPENROUTER_API_KEY` and how to set it.
- **Provider failure** (depleted credits, unknown model, rate limit) → after retries, a `RuntimeError` whose message **contains the provider's own reason** (no generic "extraction failed"). The user can act without reading source.
- **No filing found** → `ValueError` ("No 10-K/20-F for <symbol>") after the 10-K→20-F fallback.
- **No usable XBRL** → not an error: `{"data": {}, "xbrl_available": false}`.
- **CLI** mirrors these: prints a readable error to stderr and exits non-zero.

## Maintainer path — "is it still working?" (self-service)

1. **Every push** → offline CI runs (mocked, free) → logic regressions caught immediately.
2. **Weekly** → live health-check CI runs a real `extract("NVDA", …)` + `extract_xbrl("NVDA")` → green = still working; red = an external dependency drifted (an email/Actions alert), the same failure class that motivated this revival.
3. **Release** → tag/Release `vX.Y.Z` on GitHub → `workflow.yml` publishes that version to PyPI via OIDC. One action, version = tag.

## Docs structure

- `README.md` — the install → configure (OpenRouter) → quickstart → custom-preset → CLI flow (kept in sync with this IA).
- `CONTEXT.md` — domain glossary.
- `docs/PRD.md`, `docs/IA.md`, `docs/DECISIONS.md` — living planning docs.
