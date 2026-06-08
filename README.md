<div align="center">

# SEC-Analyzer

**Extract structured data from SEC filings using LLM structured output + Pydantic presets.**

Turn any SEC filing (10-K, 10-Q, 20-F, DEF 14A, ...) into structured JSON: define a Pydantic model, and the library returns data matching it.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](#)

[Installation](#installation) · [Quick Start](#quick-start) · [Custom Presets](#custom-presets) · [API Reference](#api-reference) · [CLI](#cli)

</div>

---

## Why This Library?

SEC filings contain valuable data: supply chains, revenue concentration, executive compensation, risk factors, market risk, inventory composition, and purchase obligations. Traditional parsing breaks because every filing has a different shape.

SEC-Analyzer uses **LLM structured output** through **OpenRouter** to extract exactly the data you define in a **Pydantic Preset**. The Model reads the Filing and fills in your schema. No regex, no HTML parsing, no custom post-processing.

```python
from sec_analyzer import extract
from sec_analyzer.presets import SupplyChain

result = extract("NVDA", preset=SupplyChain)
print(result["data"]["suppliers"])
# [{'entity': 'Taiwan Semiconductor Manufacturing Company Limited',
#   'relationship': 'foundry for semiconductor wafers',
#   'context': 'We utilize foundries, such as TSMC and Samsung...'}, ...]
```

---

## Installation

```bash
pip install sec-analyzer
```

Requires Python 3.10+ and an [OpenRouter API key](https://openrouter.ai/keys).

---

## Quick Start

### 1. Set your API key

```bash
export OPENROUTER_API_KEY="your-openrouter-key-here"
export EDGAR_IDENTITY="YourApp/1.0 your@email.com"
```

Or create a `.env` file:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key-here
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_REASONING_EFFORT=none
EDGAR_IDENTITY=YourApp/1.0 your@email.com
```

### 2. Extract data

```python
from sec_analyzer import extract
from sec_analyzer.presets import SupplyChain

# Latest 10-K
result = extract("NVDA", preset=SupplyChain)

# Specific form
result = extract("TSM", preset=SupplyChain, form="20-F")

# Specific filing date
result = extract("AAPL", preset=SupplyChain, filing_date="2025-10-30")
```

### 3. Use the result

```python
filing = result["filing"]
# {'form': '10-K', 'filing_date': '2026-02-25', 'accession_number': '...', 'filing_url': '...'}

data = result["data"]
print(f"Suppliers: {len(data['suppliers'])}")
print(f"Customers: {len(data['customers'])}")
print(f"Single-source deps: {len(data['single_source_dependencies'])}")
```

---

## Custom Presets

The main extension point is a **Preset**: a Pydantic `BaseModel` subclass that defines the Extraction schema.

### Basic custom preset

```python
from pydantic import BaseModel, Field
from sec_analyzer import extract

class RiskFactors(BaseModel):
    regulatory_risks: list[dict] = Field(
        default_factory=list,
        description="Government regulations that could impact the business"
    )
    litigation: list[dict] = Field(
        default_factory=list,
        description="Pending lawsuits and legal proceedings"
    )
    cybersecurity_risks: list[dict] = Field(
        default_factory=list,
        description="Data breach and cybersecurity threats"
    )

result = extract("META", preset=RiskFactors)
```

When no `__prompt__` is defined, the library auto-generates a prompt from your field descriptions.

### Advanced: custom prompt

For more control, add a `__prompt__` class variable:

```python
from typing import ClassVar
from pydantic import BaseModel, Field

class ExecutiveComp(BaseModel):
    __prompt__: ClassVar[str] = """\
You are analyzing a DEF 14A proxy statement for {company_name}.
Extract executive compensation data from the Summary Compensation Table
and related disclosure sections.

Rules:
1. Include only Named Executive Officers (NEOs)
2. All dollar amounts in exact figures from the filing
3. Include stock awards, option awards, and non-equity incentive plan separately

Filing text:
{filing_text}
"""

    executives: list[dict] = Field(description="NEO compensation details")
    equity_awards: list[dict] = Field(description="Stock and option grant details")

result = extract("AAPL", preset=ExecutiveComp, form="DEF 14A")
```

The `{company_name}` and `{filing_text}` placeholders are filled automatically.

---

## Built-in Presets

### `SupplyChain`

Extracts 11 categories of supply chain intelligence from 10-K/10-Q/20-F filings:

| Category | Description |
|----------|-------------|
| `suppliers` | Companies supplying products/materials/services |
| `customers` | Companies purchasing products/services |
| `single_source_dependencies` | Components with sole-source suppliers |
| `geographic_concentration` | Manufacturing/sourcing location concentration |
| `capacity_constraints` | Production limitations and lead times |
| `supply_chain_risks` | Disruption risks (tariffs, shortages, geopolitical) |
| `revenue_concentration` | Customer/segment revenue % from Notes |
| `geographic_revenue` | Revenue by country/region from Notes |
| `purchase_obligations` | Commitments and take-or-pay contracts |
| `market_risk_disclosures` | Commodity/FX/interest rate exposures (Item 7A) |
| `inventory_composition` | Raw materials/WIP/finished goods breakdown |

---

## API Reference

### `extract(symbol, preset, form="10-K", filing_date=None, max_chars=2_000_000, api_key=None, model=None)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | str | Ticker symbol (e.g., "NVDA") |
| `preset` | BaseModel class | Pydantic model defining the Extraction schema |
| `form` | str | Filing Form. Auto-fallback 10-K -> 20-F |
| `filing_date` | str | Specific date (YYYY-MM-DD). None = latest |
| `max_chars` | int | Max filing markdown length |
| `api_key` | str | OpenRouter API key. Falls back to `OPENROUTER_API_KEY` |
| `model` | str | OpenRouter Model id. Falls back to `OPENROUTER_MODEL`, then `deepseek/deepseek-v4-flash` |

**Returns** `{"filing": {...}, "data": {...}}`

`data` is the validated Preset dump in python mode.

### `extract_xbrl(symbol, form="10-K")`

Extracts quantitative XBRL data when available and returns:

```python
{"filing": {...}, "data": {...}, "xbrl_available": True}
```

If no usable XBRL data is available, `xbrl_available` is `False`.

---

## CLI

```bash
# Supply chain extraction (default)
sec-analyzer NVDA

# Specific form
sec-analyzer TSM --form 20-F

# Compact JSON
sec-analyzer NVDA --json

# Specific filing date
sec-analyzer AAPL --filing-date 2025-10-30

# Custom Preset
sec-analyzer NVDA --preset my_package.presets:MyPreset --json
```

On failure, the CLI exits non-zero and prints a readable JSON error to stderr.

---

## How It Works

```text
1. edgartools finds the Filing on SEC EDGAR
2. The Filing is converted to markdown
3. The full markdown + raw Pydantic JSON schema are sent to OpenRouter
4. The selected Model returns structured JSON matching the schema
5. Pydantic validates and returns typed data
```

The default Model is `deepseek/deepseek-v4-flash`. It was selected by benchmark with reasoning off because it was faster, cheaper, and more reliable for strict Extraction than the tested alternatives. Set `OPENROUTER_MODEL` or pass `model=` to choose a different Model.

Structured output is requested with OpenRouter's OpenAI-compatible `json_schema` response format in strict mode. Reasoning is disabled by default by omitting the reasoning field entirely. To opt in, set `OPENROUTER_REASONING_EFFORT` to `minimal`, `low`, `medium`, `high`, or `xhigh`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Yes | - | OpenRouter API key |
| `OPENROUTER_MODEL` | No | `deepseek/deepseek-v4-flash` | OpenRouter Model id |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | Alternate OpenRouter-compatible base URL |
| `OPENROUTER_REASONING_EFFORT` | No | `none` | Reasoning effort: `none`, `minimal`, `low`, `medium`, `high`, or `xhigh` |
| `EDGAR_IDENTITY` | No | `SECAnalyzer/1.0 user@example.com` | SEC EDGAR identity string |

See `.env.example` for a copyable template.

---

## Disclaimer

This project is **not affiliated with the SEC, EDGAR, or OpenRouter**. Filing data comes from SEC EDGAR public records. LLM extraction may contain errors; always verify critical data against the original Filing.

This tool is for **research and educational purposes only**. It is not financial advice.

---

## License

MIT
