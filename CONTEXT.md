# SEC-Analyzer

Extract structured data from SEC filings using LLM structured output + Pydantic presets. A library + CLI that turns any SEC filing into JSON matching a schema you define.

## Language

**Filing**:
A single document a company submits to SEC EDGAR (e.g. 10-K, 10-Q, 20-F, DEF 14A). Loaded via edgartools and converted to markdown for the LLM.
_Avoid_: report, document, submission.

**Form**:
The type of a **Filing** (`10-K`, `10-Q`, `20-F`, `DEF 14A`, …). 10-K is the US annual report; 20-F is its foreign-issuer equivalent (auto-fallback target when a ticker has no 10-K).
_Avoid_: filing type, report type.

**Preset**:
A Pydantic `BaseModel` subclass that defines an **Extraction** schema — its fields, descriptions, and an optional `__prompt__` class variable. The user-facing extensibility point: define a Preset, get that exact JSON back. `SupplyChain` is the built-in Preset. **Schema convention:** entity-bearing list items use the field name **`entity`** (not `name`/`company`) — a load-bearing strict-schema invariant (the benchmark showed weaker models drift to `name` and fail strict validation).
_Avoid_: schema, model (ambiguous), template.

**Extraction**:
The act (and result) of turning a **Filing** into structured data matching a **Preset**, via LLM **Structured output**. Returns `{"filing": <metadata>, "data": <preset fields>}`.
_Avoid_: parse, scrape, analysis.

**Structured output**:
The LLM feature that forces the response to conform to a JSON Schema. Used in `strict` mode via OpenRouter's `response_format`. The Preset's `model_json_schema()` is sent as the schema.
_Avoid_: JSON mode, function calling.

**Provider** / **OpenRouter**:
The LLM gateway. OpenRouter exposes many models behind one OpenAI-compatible API (`https://openrouter.ai/api/v1`). The single LLM backend; configured by `OPENROUTER_API_KEY`.
_Avoid_: vendor, backend (ambiguous).

**Model**:
The specific LLM id used for an **Extraction** (e.g. `deepseek/deepseek-v4-flash`). Selectable per call or via `OPENROUTER_MODEL`.

**XBRL extraction**:
Pulling standardized quantitative facts (US-GAAP tags) directly from a Filing's XBRL data — **no LLM**. A deterministic, ground-truth quantitative supplement to LLM **Extraction**. Exposed as `extract_xbrl()`.
_Avoid_: financials parse, fundamentals.

**Identity** (`EDGAR_IDENTITY`):
The contact string SEC requires on every EDGAR request (`"App/1.0 you@email.com"`). Falls back to a default if unset.

**Supply chain intelligence**:
The domain of the built-in `SupplyChain` Preset: suppliers, customers, single-source dependencies, geographic concentration, capacity constraints, risks, revenue/geographic concentration, purchase obligations, market-risk, inventory composition.

## Relationships

- A **Company** (by ticker) has many **Filings**; an **Extraction** selects the latest **Filing** of a **Form** (or one by date).
- A **Preset** defines what an **Extraction** produces; one library, many Presets (built-in + user-defined `module:ClassName`).
- **LLM Extraction** (broad, qualitative) and **XBRL extraction** (narrow, quantitative ground-truth) both produce structured **data**; they cross-check each other.
- An **Extraction** sends a **Filing**'s markdown + a **Preset**'s schema to a **Model** via the **Provider**, and validates the reply back into the **Preset**.

## Example dialogue

> **Dev:** "When `extract()` finds no 10-K, does it fail?"
> **PM:** "No — for a foreign issuer it should auto-fallback to the **20-F Form** before giving up."

> **Dev:** "Is **XBRL extraction** just the quantitative fields of the `SupplyChain` **Preset**?"
> **PM:** "It overlaps but it's a separate path — deterministic US-GAAP tags, no **Model** involved. It's the ground truth we check the LLM against."

## Flagged ambiguities

- "model" meant both the LLM (**Model**) and a Pydantic class — resolved: a Pydantic class defining extraction is a **Preset**; "**Model**" is the LLM only.
- "backend" was used for both the SEC loader and the LLM — resolved: the LLM gateway is the **Provider** (OpenRouter); edgartools is just the filing loader.
