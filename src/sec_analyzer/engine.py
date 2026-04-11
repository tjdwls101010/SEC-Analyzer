"""Core extraction engine: edgartools filing load + Gemini structured output."""

from __future__ import annotations

import os
import re
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

_MAX_MARKDOWN_CHARS = 2_000_000


def _init_edgar(identity: str | None = None):
    """Initialize edgartools SEC identity."""
    from edgar import set_identity

    identity = identity or os.environ.get(
        "EDGAR_IDENTITY", "SECAnalyzer/1.0 user@example.com"
    )
    set_identity(identity)


def _get_filing(symbol: str, form: str = "10-K", filing_date: str | None = None):
    """Search latest filing via edgartools. Auto-fallback 10-K -> 20-F.

    Returns:
        tuple: (filing, metadata_dict, company_name)
    """
    from edgar import Company

    _init_edgar()
    company = Company(symbol)

    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            filings = company.get_filings(form=form)
            if len(filings) == 0 and form == "10-K":
                filings = company.get_filings(form="20-F")
                form = "20-F"
            if len(filings) == 0:
                raise ValueError(f"No {form} filing found for {symbol}")

            if filing_date:
                for f in filings:
                    if str(f.filing_date) == filing_date:
                        filing = f
                        break
                else:
                    filing = filings[0]
            else:
                filing = filings[0]

            metadata = {
                "form": form,
                "filing_date": str(filing.filing_date),
                "accession_number": filing.accession_number,
                "filing_url": filing.filing_url,
            }
            return filing, metadata, company.name
        except ValueError:
            raise
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2**attempt)
                continue
    raise RuntimeError(f"edgartools failed after {retries} attempts: {last_error}")


def _get_markdown(filing, max_chars: int = _MAX_MARKDOWN_CHARS) -> str:
    """Convert filing to markdown with safe truncation."""
    md = filing.markdown()
    if len(md) > max_chars:
        md = md[:max_chars]
    return md


def _build_default_prompt(preset_cls: type[BaseModel], company_name: str) -> str:
    """Build a default extraction prompt from Pydantic field descriptions."""
    schema = preset_cls.model_json_schema()
    fields_desc = []
    for name, prop in schema.get("properties", {}).items():
        desc = prop.get("description", name)
        fields_desc.append(f"- {name}: {desc}")

    return f"""\
You are a financial analyst extracting structured data from SEC filings.
Extract entities and data exactly as stated in the filing text.

Filing company: {company_name}

Extract the following fields:
{chr(10).join(fields_desc)}

Rules:
1. Use exact names and figures from the filing — do not paraphrase or invent.
2. For context fields, copy 1-3 relevant sentences verbatim from the filing.
3. If a field has no relevant data, return an empty list or null.

Extract from this SEC filing text:

{{filing_text}}
"""


def _extract_with_llm(
    filing_text: str,
    preset_cls: type[BaseModel],
    company_name: str = "",
    api_key: str | None = None,
    model: str | None = None,
) -> BaseModel | None:
    """Extract structured data using Gemini structured output + Pydantic.

    Returns:
        Pydantic model instance, or None on failure.
    """
    from google import genai

    api_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY not set. Pass api_key parameter or set the environment variable."
        )

    model_id = model or os.environ.get("GOOGLE_MODEL", "gemini-2.5-flash")

    # Build prompt: use preset's __prompt__ if available, else generate default
    custom_prompt = getattr(preset_cls, "__prompt__", None)
    if custom_prompt:
        prompt = custom_prompt.format(
            company_name=company_name or "Unknown",
            filing_text=filing_text,
        )
    else:
        template = _build_default_prompt(preset_cls, company_name or "Unknown")
        prompt = template.format(filing_text=filing_text)

    gen_config = {
        "response_mime_type": "application/json",
        "response_json_schema": preset_cls.model_json_schema(),
        "temperature": 0,
    }

    thinking_level = os.environ.get("GOOGLE_THINKING_LEVEL", "low")
    if thinking_level and thinking_level.lower() in ("low", "medium", "high", "minimal"):
        from google.genai import types
        gen_config["thinking_config"] = types.ThinkingConfig(
            thinking_level=thinking_level.lower()
        )

    client = genai.Client(api_key=api_key)
    retries = 3

    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=gen_config,
            )
            return preset_cls.model_validate_json(response.text)
        except Exception as e:
            print(
                f"[sec-analyzer] LLM attempt {attempt}/{retries} failed: {e}",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            return None


def extract(
    symbol: str,
    preset: type[BaseModel],
    form: str = "10-K",
    filing_date: str | None = None,
    max_chars: int = _MAX_MARKDOWN_CHARS,
    api_key: str | None = None,
    model: str | None = None,
) -> dict:
    """Extract structured data from an SEC filing using a Pydantic preset.

    Args:
        symbol: Ticker symbol (e.g., "NVDA", "AAPL", "TSM").
        preset: Pydantic BaseModel class defining the extraction schema.
            Optionally include a `__prompt__` class variable with a custom
            extraction prompt (use {company_name} and {filing_text} placeholders).
        form: Filing form type ("10-K", "10-Q", "20-F", "DEF 14A", etc.).
            Auto-fallback from 10-K to 20-F for foreign issuers.
        filing_date: Specific filing date (YYYY-MM-DD). None for latest.
        max_chars: Maximum filing markdown length.
        api_key: Google API key. Falls back to GOOGLE_API_KEY env var.
        model: Gemini model ID. Falls back to GOOGLE_MODEL env var.

    Returns:
        dict with "filing" (metadata) and "data" (extracted fields).
    """
    from dotenv import load_dotenv

    load_dotenv()

    filing, metadata, company_name = _get_filing(symbol, form, filing_date)
    markdown = _get_markdown(filing, max_chars)

    result = _extract_with_llm(
        filing_text=markdown,
        preset_cls=preset,
        company_name=company_name,
        api_key=api_key,
        model=model,
    )

    if result is None:
        raise RuntimeError(f"LLM extraction failed for {symbol} ({metadata['form']})")

    return {
        "filing": metadata,
        "data": result.model_dump(),
    }


# ---------------------------------------------------------------------------
# XBRL structured data extraction
# ---------------------------------------------------------------------------

def extract_xbrl(symbol: str, form: str = "10-K") -> dict:
    """Extract structured quantitative data from XBRL tags.

    Extracts 4 categories using standardized US-GAAP XBRL tags:
    - revenue_concentration: Customer/segment revenue % (ConcentrationRiskPercentage)
    - geographic_revenue: Revenue by country/region
    - inventory_composition: Raw materials / WIP / finished goods
    - purchase_obligations: Unconditional purchase commitments

    Args:
        symbol: Ticker symbol.
        form: Filing form type.

    Returns:
        dict with "filing" metadata and "data" containing available categories.
        Empty categories are omitted.
    """
    from dotenv import load_dotenv
    load_dotenv()

    filing, metadata, _ = _get_filing(symbol, form)

    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            return {"filing": metadata, "data": {}, "xbrl_available": False}
    except Exception:
        return {"filing": metadata, "data": {}, "xbrl_available": False}

    try:
        import pandas as pd
        df = xbrl.instance.facts.reset_index()
    except Exception:
        return {"filing": metadata, "data": {}, "xbrl_available": False}

    supplements = {}

    # --- Revenue Concentration ---
    conc = df[df["concept"].astype(str).str.contains(
        "ConcentrationRiskPercentage", case=False, na=False)]
    if len(conc) > 0:
        benchmark_col = "us-gaap:ConcentrationRiskByBenchmarkAxis"
        if benchmark_col in conc.columns:
            conc = conc[conc[benchmark_col].astype(str).str.contains(
                "Revenue", case=False, na=False)]
        if "end_date" in conc.columns and len(conc) > 0:
            latest_date = conc["end_date"].max()
            conc = conc[conc["end_date"] == latest_date]

        entries = []
        seen = set()
        for _, row in conc.iterrows():
            customer = str(row.get("srt:MajorCustomersAxis", ""))
            if not customer or customer == "nan":
                continue
            name = customer.split(":")[-1].replace("Member", "")
            name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
            _GEO = ("Based End Customers", "Region", "Country", "Americas",
                    "Europe", "Asia", "Pacific", "United States", "China", "Japan")
            if any(kw.lower() in name.lower() for kw in _GEO):
                continue
            if name in seen:
                continue
            seen.add(name)
            try:
                pct = round(float(row["value"]) * 100, 2)
            except (ValueError, TypeError):
                pct = None
            entries.append({"entity": name, "revenue_pct": pct,
                           "source": "xbrl", "end_date": str(row.get("end_date", ""))})
        if entries:
            supplements["revenue_concentration"] = entries

    # --- Geographic Revenue ---
    geo_col = "srt:StatementGeographicalAxis"
    if geo_col in df.columns:
        geo = df[(df[geo_col].notna()) &
                 (df["concept"].astype(str).str.contains("Revenue", case=False, na=False))]
        if len(geo) > 0:
            _rev_patterns = ["RevenueFromContractWithCustomer", r"^us-gaap:Revenues$"]
            total_rev = None
            for pat in _rev_patterns:
                rows = df[
                    (df["concept"].astype(str).str.contains(pat, case=False, na=False)) &
                    (~df["concept"].astype(str).str.contains(
                        "TextBlock|Policy|Description|Percentage|Cost", case=False, na=False)) &
                    (df[geo_col].isna()) & (df["period_type"] == "duration")
                ].copy()
                if len(rows) > 0:
                    try:
                        rows["_val"] = pd.to_numeric(rows["value"], errors="coerce")
                        rows = rows.dropna(subset=["_val"])
                        if len(rows) > 0:
                            latest = rows[rows["end_date"] == rows["end_date"].max()]
                            total_rev = float(latest["_val"].max())
                            break
                    except Exception:
                        continue

            entries = []
            seen = set()
            _COUNTRY_MAP = {"US": "United States", "CN": "China", "JP": "Japan",
                           "TW": "Taiwan", "KR": "South Korea", "DE": "Germany",
                           "GB": "United Kingdom", "IN": "India"}
            for _, row in geo.iterrows():
                region = str(row[geo_col]).split(":")[-1].replace("Member", "")
                region = re.sub(r"([a-z])([A-Z])", r"\1 \2", region)
                region = _COUNTRY_MAP.get(region, region)
                try:
                    amount = float(row["value"])
                except (ValueError, TypeError):
                    continue
                end_date = str(row.get("end_date", ""))
                key = f"{region}_{end_date}"
                if key in seen:
                    continue
                seen.add(key)
                pct = round(amount / total_rev * 100, 2) if total_rev else None
                amt_str = f"${amount/1e9:.1f}B" if amount >= 1e9 else f"${amount/1e6:.0f}M"
                entries.append({"region": region, "revenue_pct": pct,
                               "revenue_amount": amt_str, "source": "xbrl", "end_date": end_date})
            if entries:
                entries.sort(key=lambda x: x["end_date"], reverse=True)
                if entries:
                    first_period = entries[0]["end_date"]
                    entries = [e for e in entries if e["end_date"] == first_period]
                supplements["geographic_revenue"] = entries

    # --- Inventory Composition ---
    inv_concepts = {
        "InventoryRawMaterialsAndSupplies": "raw_materials",
        "InventoryRawMaterials": "raw_materials",
        "InventoryWorkInProcess": "work_in_progress",
        "InventoryFinishedGoods": "finished_goods",
        "InventoryFinishedGoodsAndWorkInProcess": "finished_goods",
    }
    inv_total_row = df[df["concept"].astype(str).str.contains(
        r"^us-gaap:InventoryNet$", case=False, na=False)]
    inv_total = None
    if len(inv_total_row) > 0:
        try:
            inv_total = float(inv_total_row.iloc[0]["value"])
        except (ValueError, TypeError):
            pass

    inv_entries = []
    comp_total = 0.0
    for suffix, category in inv_concepts.items():
        rows = df[df["concept"].astype(str).str.contains(suffix, case=False, na=False)]
        if len(rows) > 0:
            try:
                amount = float(rows.iloc[0]["value"])
            except (ValueError, TypeError):
                continue
            comp_total += amount
            amt_str = f"${amount/1e9:.1f}B" if amount >= 1e9 else f"${amount/1e6:.0f}M"
            inv_entries.append({"category": category, "amount": amt_str,
                               "_raw": amount, "source": "xbrl"})
    if inv_entries:
        denom = inv_total if inv_total and comp_total <= inv_total * 1.05 else comp_total
        for e in inv_entries:
            raw = e.pop("_raw")
            e["pct_of_total"] = round(raw / denom * 100, 2) if denom else None
        supplements["inventory_composition"] = inv_entries

    # --- Purchase Obligations ---
    po_rows = df[df["concept"].astype(str).str.contains(
        "UnrecordedUnconditionalPurchaseObligation", case=False, na=False)]
    po_rows = po_rows[~po_rows["concept"].astype(str).str.contains(
        "TextBlock|Policy", case=False, na=False)]
    if len(po_rows) > 0:
        po_entries = []
        for _, row in po_rows.iterrows():
            concept = str(row["concept"])
            try:
                amount = float(row["value"])
            except (ValueError, TypeError):
                continue
            amt_str = f"${amount/1e9:.1f}B" if amount >= 1e9 else f"${amount/1e6:.0f}M"
            timeframe = ""
            for label, tf in [("BalanceSheetAmount", "total"),
                              ("FirstAnniversary", "year 1"), ("SecondAnniversary", "year 2"),
                              ("ThirdAnniversary", "year 3"), ("FourthAnniversary", "year 4"),
                              ("FifthAnniversary", "year 5"), ("AfterFiveYears", "after year 5")]:
                if label in concept:
                    timeframe = tf
                    break
            po_entries.append({"obligation_type": "unconditional purchase obligation",
                              "amount": amt_str, "timeframe": timeframe, "source": "xbrl"})
        if po_entries:
            supplements["purchase_obligations"] = po_entries

    return {
        "filing": metadata,
        "data": supplements,
        "xbrl_available": True,
    }
