<div align="center">

<img src="https://i.namu.wiki/i/HbVpHEsWi0aG30L2PEWRL9FEA0P7Vf-iLYm0QPbH1iOGJabk3vYcDQz1Uxo1DX3OaujOJWX62rs6QgqXFOybLw.svg" width="120" alt="SEC">

# SEC-Analyzer

**Extract structured data from SEC filings using LLM + Pydantic presets.**

Turn any SEC filing (10-K, 10-Q, 20-F, DEF 14A, ...) into structured JSON — define a Pydantic model, and the library does the rest.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](#)

[Installation](#installation) · [Quick Start](#quick-start) · [Custom Presets](#custom-presets) · [API Reference](#api-reference) · [CLI](#cli)

</div>

![](https://github.com/tjdwls101010/DUMOK/blob/main/Images/gemini-3-pro-1774265890176ioxhdiv1w.png?raw=true)

---

## Why This Library?

SEC filings contain invaluable data — supply chains, revenue concentration, executive compensation, risk factors — but every filing has a different format. Traditional parsing breaks constantly.

This library uses **LLM structured output** (Gemini) to extract exactly the data you define in a **Pydantic model**. The LLM reads the filing and fills in your schema. No regex, no HTML parsing, no breakage.

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

Requires Python 3.10+ and a [Google AI API key](https://ai.google.dev/).

---

## Quick Start

### 1. Set your API key

```bash
export GOOGLE_API_KEY="your-key-here"
export EDGAR_IDENTITY="YourApp/1.0 your@email.com"
```

Or create a `.env` file:
```
GOOGLE_API_KEY=your-key-here
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

The real power: **define your own Pydantic model** to extract anything.

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

For expert-level control, add a `__prompt__` class variable:

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
| `preset` | BaseModel class | Pydantic model defining extraction schema |
| `form` | str | Filing type. Auto-fallback 10-K → 20-F |
| `filing_date` | str | Specific date (YYYY-MM-DD). None = latest |
| `max_chars` | int | Max filing markdown length |
| `api_key` | str | Google API key (fallback: `GOOGLE_API_KEY` env) |
| `model` | str | Gemini model (fallback: `GOOGLE_MODEL` env, default: `gemini-2.5-flash`) |

**Returns** `{"filing": {...}, "data": {...}}`

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
```

---

## How It Works

```
1. edgartools finds the filing on SEC EDGAR
2. Filing converted to markdown (tables preserved)
3. Full markdown + Pydantic schema sent to Gemini
4. Gemini returns structured JSON matching the schema
5. Pydantic validates and returns typed data
```

The key insight: Gemini's **structured output** mode forces the response to match your Pydantic schema exactly. No post-processing, no regex, no parsing.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_API_KEY` | Yes | - | Google AI API key |
| `EDGAR_IDENTITY` | No | `SECAnalyzer/1.0 user@example.com` | SEC EDGAR User-Agent |
| `GOOGLE_MODEL` | No | `gemini-2.5-flash` | Gemini model ID |

---

## Disclaimer

This project is **not affiliated with the SEC, EDGAR, or Google**. Filing data comes from SEC EDGAR (public). LLM extraction may contain errors — always verify critical data against the original filing.

This tool is for **research and educational purposes only**. It is not financial advice.

---

## License

MIT
