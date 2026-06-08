# Benchmark — model & reasoning selection (2026-06-08)

Why the default is **`deepseek/deepseek-v4-flash`, reasoning `none`**. Re-run this when models change.

## Method

- **Task:** real `SupplyChain` extraction from live SEC filings via OpenRouter, strict `json_schema` structured output (raw Pydantic schema), `temperature=0`.
- **Grid:** flash × reasoning effort `{none, low, medium, high, xhigh}` over **10 diverse tickers** (NVDA, AAPL, CAT, F, TSM, ASML, JPM, CRWD, PFE, WMT — semi/consumer/industrial/auto/foreign-20F/bank/SaaS/pharma/retail), plus **pro × none** over the same 10.
- **Metrics:** success/failure (did it return schema-valid JSON), latency, cost, field coverage. Quality judged by reading actual extracted content, not just counts.

## Results

**flash, by reasoning effort (10 tickers):**

| effort | success | avg latency | avg cost/filing | avg fields |
|---|---|---|---|---|
| **none** | **10/10** | **35 s** | $0.020 | 5.1 |
| low | 9/10 | 60 s | $0.009 | 3.4 |
| medium | 8/10 | 67 s | $0.014 | 4.8 |
| high | 8/10 | 57 s | $0.009 | 4.5 |
| xhigh | 9/10 | 104 s | $0.012 | 5.3 |

**flash/none vs pro/none (10 tickers):**

| | flash/none | pro/none |
|---|---|---|
| success | **10/10** | 6/10 (failed NVDA, AAPL, CAT, ASML) |
| avg latency | 35 s | 46 s |
| avg cost/filing | **$0.020** | $0.36 (**~18×**) |
| avg fields | 5.1 | 5.0 (tied) |

## Decision

**flash/none.** It is the only configuration with **zero failures**, the fastest, ~18× cheaper than pro, and quality-tied. pro is not "dramatically better" (the balanced-criterion tiebreaker) — it ties on fields and outright **fails on NVDA and AAPL** — so its richer-supplier edge on a few tickers does not justify the cost/latency/unreliability. Reasoning is `none` by default but raisable via `OPENROUTER_REASONING_EFFORT`; `pro` available via `OPENROUTER_MODEL`.

## Why more reasoning made extraction *worse* (counterintuitive)

Extraction is a **scan-and-copy** task (the prompt says "use exact names, copy verbatim"), not a multi-step reasoning task. Forcing deep thinking added no better answer, only failure surface. Observed mechanisms:

1. **Token-budget exhaustion → truncated JSON.** Reasoning spends output tokens first; the JSON answer then gets cut off mid-string. (pro NVDA/AAPL = "EOF while parsing".)
2. **Format constraint vs free-form thinking.** Strict JSON forces token-level grammar; reasoning wants prose. They fight → schema drift. (F returned **markdown** `**Suppliers**…` instead of JSON; pro used field `name` instead of `entity`.)
3. **Over-deliberation drops valid entries.** The model second-guesses ("is this *really* a supplier per the rules?") and filters itself to fewer/zero fields. (AAPL high = 1 field, JPM low = 0.)
4. **Chain-of-thought leakage into data fields.** (TSM high put `…per_rule_6_which_requires…` into a risk field.)

Plus the reasoning + strict-JSON path appears **less mature for DeepSeek via OpenRouter** — flash/none never failed while every reasoning level had failures.

These failure modes are **engineering requirements** for the implementation: handle `content=None` by retrying, surface the real provider error, keep retries.

## Caveats & future work

- Single-shot extraction over very large filings is **high-variance in completeness** regardless of model (e.g. NVDA sometimes captured the financial-notes quantitative fields, sometimes not). This is an architectural limit, not a model-choice one — out of scope for the revival.
- The quantitative Notes fields (geographic revenue %, revenue concentration, inventory) that the LLM sometimes misses are covered deterministically by **`extract_xbrl()`** — by design, XBRL is the quantitative ground-truth and the LLM is the qualitative layer.
- Re-evaluate model/effort when DeepSeek or OpenRouter ship new versions, or to add other providers (GPT/Claude/Gemini are all reachable via OpenRouter).
