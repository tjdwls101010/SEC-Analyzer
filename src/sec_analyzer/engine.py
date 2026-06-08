"""Core extraction engine: edgartools filing load + OpenRouter structured output."""

from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

_MAX_MARKDOWN_CHARS = 2_000_000
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
_OPENROUTER_TIMEOUT_SECONDS = 120.0
_OPENROUTER_RETRIES = 3
_OPENROUTER_BACKOFF_BASE_SECONDS = 1.0
_OPENROUTER_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/tjdwls101010/SEC-Analyzer",
    "X-Title": "SEC-Analyzer",
}


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_openrouter_api_key(api_key: str | None = None) -> str:
    resolved = _non_empty(api_key) or _non_empty(os.environ.get("OPENROUTER_API_KEY"))
    if not resolved:
        raise ValueError(
            "OPENROUTER_API_KEY not set. Pass api_key=... or set "
            "OPENROUTER_API_KEY in your environment or .env file."
        )
    return resolved


def _resolve_openrouter_model(model: str | None = None) -> str:
    return (
        _non_empty(model)
        or _non_empty(os.environ.get("OPENROUTER_MODEL"))
        or _OPENROUTER_DEFAULT_MODEL
    )


def _resolve_openrouter_base_url() -> str:
    return _non_empty(os.environ.get("OPENROUTER_BASE_URL")) or _OPENROUTER_BASE_URL


def _resolve_openrouter_reasoning_effort() -> str:
    effort = (_non_empty(os.environ.get("OPENROUTER_REASONING_EFFORT")) or "none").lower()
    if effort not in _OPENROUTER_REASONING_EFFORTS:
        return "none"
    return effort


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(_OPENROUTER_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))


def _response_value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _first_choice(choices: Any) -> Any:
    if not choices:
        return None
    try:
        return choices[0]
    except (IndexError, KeyError, TypeError):
        return None


def _format_provider_exception(exc: Exception, api_status_error_type: type[Exception]) -> str:
    parts = [str(exc) or repr(exc)]
    if isinstance(exc, api_status_error_type):
        body = getattr(exc, "body", None)
        if body is not None:
            body_text = str(body)
            if body_text and body_text not in parts[0]:
                parts.append(f"body: {body_text}")
    return " | ".join(parts)


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
) -> BaseModel:
    """Extract structured data using OpenRouter structured output + Pydantic."""
    from openai import APIStatusError, OpenAI
    from pydantic import ValidationError

    resolved_api_key = _resolve_openrouter_api_key(api_key)
    model_id = _resolve_openrouter_model(model)
    reasoning_effort = _resolve_openrouter_reasoning_effort()

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

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": preset_cls.__name__,
            "strict": True,
            "schema": preset_cls.model_json_schema(),
        },
    }

    client = OpenAI(
        api_key=resolved_api_key,
        base_url=_resolve_openrouter_base_url(),
        max_retries=0,
        default_headers=_OPENROUTER_HEADERS,
    )

    last_failure = ""
    failure_kinds: list[str] = []

    for attempt in range(1, _OPENROUTER_RETRIES + 1):
        try:
            request_kwargs: dict[str, Any] = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": response_format,
                "temperature": 0,
                "timeout": _OPENROUTER_TIMEOUT_SECONDS,
            }
            if reasoning_effort != "none":
                request_kwargs["reasoning_effort"] = reasoning_effort

            response = client.chat.completions.create(**request_kwargs)
        except Exception as e:
            last_failure = _format_provider_exception(e, APIStatusError)
            failure_kinds.append("provider")
        else:
            top_level_error = _response_value(response, "error")
            if top_level_error:
                last_failure = f"provider returned error: {top_level_error}"
                failure_kinds.append("provider")
            else:
                choice = _first_choice(_response_value(response, "choices"))
                if choice is None:
                    last_failure = f"provider returned no choices for model {model_id}"
                    failure_kinds.append("provider")
                else:
                    message = _response_value(choice, "message")
                    if message is None:
                        last_failure = (
                            f"provider returned a choice without a message for model {model_id}"
                        )
                        failure_kinds.append("provider")
                    else:
                        refusal = _response_value(message, "refusal")
                        if refusal:
                            raise RuntimeError(
                                f"OpenRouter extraction refused for model {model_id}: {refusal}"
                            )

                        content = _response_value(message, "content")
                        if not isinstance(content, str) or not content.strip():
                            last_failure = (
                                "provider returned empty content on attempt "
                                f"{attempt}/{_OPENROUTER_RETRIES} for model {model_id}"
                            )
                            failure_kinds.append("empty")
                        else:
                            try:
                                return preset_cls.model_validate_json(content)
                            except ValidationError as e:
                                last_failure = str(e)
                                failure_kinds.append("validation")

        if attempt < _OPENROUTER_RETRIES:
            _sleep_before_retry(attempt)

    if failure_kinds and all(kind == "empty" for kind in failure_kinds):
        last_failure = (
            "provider returned empty content on all "
            f"{_OPENROUTER_RETRIES} attempts for model {model_id}"
        )

    raise RuntimeError(
        "OpenRouter extraction failed for "
        f"model {model_id} after {_OPENROUTER_RETRIES} attempts: {last_failure}"
    )


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
        api_key: OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
        model: OpenRouter model ID. Falls back to OPENROUTER_MODEL env var,
            then deepseek/deepseek-v4-flash.

    Returns:
        dict with "filing" (metadata) and "data" (extracted fields).
    """
    from dotenv import load_dotenv

    load_dotenv()

    _resolve_openrouter_api_key(api_key)

    filing, metadata, company_name = _get_filing(symbol, form, filing_date)
    markdown = _get_markdown(filing, max_chars)

    result = _extract_with_llm(
        filing_text=markdown,
        preset_cls=preset,
        company_name=company_name,
        api_key=api_key,
        model=model,
    )

    return {
        "filing": metadata,
        "data": result.model_dump(),
    }


# ---------------------------------------------------------------------------
# XBRL structured data extraction
# ---------------------------------------------------------------------------

_XBRL_NUMERIC_VALUE_COL = "_numeric_value"
_XBRL_RESOLVED_DATE_COL = "_resolved_date"
_XBRL_GEO_AXIS_COL = "dim_srt_StatementGeographicalAxis"
_XBRL_MAJOR_CUSTOMERS_COL = "dim_srt_MajorCustomersAxis"
_XBRL_BENCHMARK_COL = "dim_us-gaap_ConcentrationRiskByBenchmarkAxis"
_XBRL_COUNTRY_MAP = {
    "US": "United States",
    "CN": "China",
    "JP": "Japan",
    "TW": "Taiwan",
    "KR": "South Korea",
    "DE": "Germany",
    "GB": "United Kingdom",
    "IN": "India",
}
_XBRL_INVENTORY_CONCEPTS = (
    ("InventoryRawMaterialsAndSupplies", "raw_materials"),
    ("InventoryRawMaterials", "raw_materials"),
    ("InventoryWorkInProcess", "work_in_progress"),
    ("InventoryFinishedGoods", "finished_goods"),
    ("InventoryFinishedGoodsAndWorkInProcess", "finished_goods"),
)
_XBRL_PURCHASE_OBLIGATION_TIMEFRAMES = (
    ("BalanceSheetAmount", "total"),
    ("FirstAnniversary", "year 1"),
    ("SecondAnniversary", "year 2"),
    ("ThirdAnniversary", "year 3"),
    ("FourthAnniversary", "year 4"),
    ("FifthAnniversary", "year 5"),
    ("AfterFiveYears", "after year 5"),
)


def _xbrl_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    return text


def _xbrl_text_column(df, column: str):
    import pandas as pd

    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return df[column].astype("string")


def _prepare_xbrl_facts(df):
    import pandas as pd

    df = df.copy()
    if "numeric_value" in df.columns:
        df[_XBRL_NUMERIC_VALUE_COL] = pd.to_numeric(
            df["numeric_value"], errors="coerce"
        )
    else:
        df[_XBRL_NUMERIC_VALUE_COL] = pd.Series(
            [pd.NA] * len(df), index=df.index, dtype="Float64"
        )

    resolved_date = pd.Series(pd.NA, index=df.index, dtype="string")
    for column in ("period_end", "period_instant"):
        if column in df.columns:
            resolved_date = resolved_date.combine_first(df[column].astype("string"))
    df[_XBRL_RESOLVED_DATE_COL] = resolved_date
    return df


def _latest_rows_by_date(rows, date_column: str = _XBRL_RESOLVED_DATE_COL):
    if len(rows) == 0 or date_column not in rows.columns:
        return rows.iloc[0:0]
    dates = rows[date_column].dropna()
    if len(dates) == 0:
        return rows.iloc[0:0]
    latest_date = dates.max()
    return rows[rows[date_column] == latest_date]


def _xbrl_member_set(df, column: str) -> set[str]:
    return {
        text
        for value in _xbrl_text_column(df, column).dropna()
        if (text := _xbrl_text(value))
    }


def _xbrl_not_dimensioned(df):
    if "is_dimensioned" in df.columns:
        is_dimensioned = _xbrl_text_column(df, "is_dimensioned").str.lower()
        return is_dimensioned.isna() | is_dimensioned.isin({"false", "0"})
    return _xbrl_text_column(df, "dimension").isna() & _xbrl_text_column(
        df, "member"
    ).isna()


def _format_xbrl_member(member: Any, *, country_map: bool = False) -> str | None:
    text = _xbrl_text(member)
    if text is None:
        return None
    label = text.split(":")[-1].replace("Member", "")
    label = re.sub(r"([a-z])([A-Z])", r"\1 \2", label)
    if country_map:
        label = _XBRL_COUNTRY_MAP.get(label, label)
    return label


def _format_xbrl_amount(amount: float) -> str:
    return f"${amount/1e9:.1f}B" if amount >= 1e9 else f"${amount/1e6:.0f}M"


def _map_revenue_concentration(df) -> list[dict[str, Any]]:
    concept = _xbrl_text_column(df, "concept")
    conc = df[
        concept.str.contains("ConcentrationRiskPercentage", case=False, na=False)
        & df[_XBRL_NUMERIC_VALUE_COL].notna()
    ]
    if len(conc) == 0:
        return []

    benchmark = _xbrl_text_column(conc, _XBRL_BENCHMARK_COL)
    conc = conc[
        benchmark.str.contains(
            r"SalesRevenueNet|Revenue", case=False, na=False, regex=True
        )
        & ~benchmark.str.contains(
            "AccountsReceivable", case=False, na=False, regex=True
        )
    ]
    conc = _latest_rows_by_date(conc)
    if len(conc) == 0:
        return []

    geographic_members = _xbrl_member_set(df, _XBRL_GEO_AXIS_COL)
    entries = []
    seen = set()
    for _, row in conc.iterrows():
        customer_member = _xbrl_text(row.get(_XBRL_MAJOR_CUSTOMERS_COL))
        if customer_member is None:
            continue
        if customer_member in geographic_members:
            continue
        if _xbrl_text(row.get(_XBRL_GEO_AXIS_COL)) is not None:
            continue

        name = _format_xbrl_member(customer_member)
        if name is None or name in seen:
            continue
        seen.add(name)
        pct = round(float(row[_XBRL_NUMERIC_VALUE_COL]) * 100, 2)
        entries.append(
            {
                "entity": name,
                "revenue_pct": pct,
                "source": "xbrl",
                "end_date": _xbrl_text(row.get(_XBRL_RESOLVED_DATE_COL)) or "",
            }
        )
    return entries


def _find_total_revenue(df, latest_date: str | None) -> float | None:
    concept = _xbrl_text_column(df, "concept")
    period_type = _xbrl_text_column(df, "period_type").str.lower()
    geo_member = _xbrl_text_column(df, _XBRL_GEO_AXIS_COL)
    not_dimensioned = _xbrl_not_dimensioned(df)
    excluded = concept.str.contains(
        r"TextBlock|Policy|Description|Percentage|Cost",
        case=False,
        na=False,
        regex=True,
    )

    for pattern in ("RevenueFromContractWithCustomer", r"^us-gaap:Revenues$"):
        rows = df[
            concept.str.contains(pattern, case=False, na=False, regex=True)
            & ~excluded
            & not_dimensioned
            & geo_member.isna()
            & period_type.eq("duration")
            & df[_XBRL_NUMERIC_VALUE_COL].notna()
        ]
        if latest_date is not None:
            rows = rows[rows[_XBRL_RESOLVED_DATE_COL] == latest_date]
        else:
            rows = _latest_rows_by_date(rows)
        if len(rows) > 0:
            return float(rows[_XBRL_NUMERIC_VALUE_COL].max())
    return None


def _map_geographic_revenue(df) -> list[dict[str, Any]]:
    if _XBRL_GEO_AXIS_COL not in df.columns:
        return []

    concept = _xbrl_text_column(df, "concept")
    period_type = _xbrl_text_column(df, "period_type").str.lower()
    geo_member = _xbrl_text_column(df, _XBRL_GEO_AXIS_COL)
    excluded = concept.str.contains(
        r"TextBlock|Policy|Description|Percentage|Cost",
        case=False,
        na=False,
        regex=True,
    )
    geo = df[
        geo_member.notna()
        & concept.str.contains("Revenue", case=False, na=False)
        & ~excluded
        & period_type.eq("duration")
        & df[_XBRL_NUMERIC_VALUE_COL].notna()
    ]
    geo = _latest_rows_by_date(geo)
    if len(geo) == 0:
        return []

    latest_date = _xbrl_text(geo[_XBRL_RESOLVED_DATE_COL].dropna().max())
    total_revenue = _find_total_revenue(df, latest_date)

    entries = []
    seen = set()
    for _, row in geo.iterrows():
        region = _format_xbrl_member(row.get(_XBRL_GEO_AXIS_COL), country_map=True)
        if region is None:
            continue
        amount = float(row[_XBRL_NUMERIC_VALUE_COL])
        end_date = _xbrl_text(row.get(_XBRL_RESOLVED_DATE_COL)) or ""
        key = (region, end_date)
        if key in seen:
            continue
        seen.add(key)
        pct = round(amount / total_revenue * 100, 2) if total_revenue else None
        entries.append(
            {
                "region": region,
                "revenue_pct": pct,
                "revenue_amount": _format_xbrl_amount(amount),
                "source": "xbrl",
                "end_date": end_date,
            }
        )
    return entries


def _map_inventory_composition(df) -> list[dict[str, Any]]:
    concept = _xbrl_text_column(df, "concept")
    candidate = concept.str.contains(
        r"^us-gaap:InventoryNet$", case=False, na=False, regex=True
    )
    for suffix, _ in _XBRL_INVENTORY_CONCEPTS:
        candidate = candidate | concept.str.contains(
            suffix, case=False, na=False, regex=True
        )

    period_instant = _xbrl_text_column(df, "period_instant")
    latest_rows = _latest_rows_by_date(
        df[candidate & period_instant.notna() & df[_XBRL_NUMERIC_VALUE_COL].notna()],
        "period_instant",
    )
    if len(latest_rows) == 0:
        return []

    latest_concept = _xbrl_text_column(latest_rows, "concept")
    total_rows = latest_rows[
        latest_concept.str.contains(
            r"^us-gaap:InventoryNet$", case=False, na=False, regex=True
        )
    ]
    denominator = None
    if len(total_rows) > 0:
        denominator = float(total_rows[_XBRL_NUMERIC_VALUE_COL].max())

    entries = []
    seen_categories = set()
    for suffix, category in _XBRL_INVENTORY_CONCEPTS:
        if category in seen_categories:
            continue
        rows = latest_rows[
            _xbrl_text_column(latest_rows, "concept").str.contains(
                suffix, case=False, na=False, regex=True
            )
        ]
        if len(rows) == 0:
            continue
        amount = float(rows.iloc[0][_XBRL_NUMERIC_VALUE_COL])
        pct = round(amount / denominator * 100, 2) if denominator else None
        entries.append(
            {
                "category": category,
                "amount": _format_xbrl_amount(amount),
                "source": "xbrl",
                "pct_of_total": pct,
            }
        )
        seen_categories.add(category)

    return entries


def _map_purchase_obligations(df) -> list[dict[str, Any]]:
    concept = _xbrl_text_column(df, "concept")
    po_rows = df[
        concept.str.contains(
            "UnrecordedUnconditionalPurchaseObligation", case=False, na=False
        )
        & ~concept.str.contains(r"TextBlock|Policy", case=False, na=False, regex=True)
        & _xbrl_text_column(df, "period_instant").notna()
        & df[_XBRL_NUMERIC_VALUE_COL].notna()
    ]
    po_rows = _latest_rows_by_date(po_rows, "period_instant")
    if len(po_rows) == 0:
        return []

    entries = []
    for _, row in po_rows.iterrows():
        concept_name = str(row["concept"])
        timeframe = ""
        for fragment, label in _XBRL_PURCHASE_OBLIGATION_TIMEFRAMES:
            if fragment in concept_name:
                timeframe = label
                break
        amount = float(row[_XBRL_NUMERIC_VALUE_COL])
        entries.append(
            {
                "obligation_type": "unconditional purchase obligation",
                "amount": _format_xbrl_amount(amount),
                "timeframe": timeframe,
                "source": "xbrl",
            }
        )
    return entries


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
        df = xbrl.facts.to_dataframe()
        if df is None or len(df) == 0:
            return {"filing": metadata, "data": {}, "xbrl_available": False}
        df = _prepare_xbrl_facts(df)
    except Exception:
        return {"filing": metadata, "data": {}, "xbrl_available": False}

    supplements = {}

    # --- Revenue Concentration ---
    entries = _map_revenue_concentration(df)
    if entries:
        supplements["revenue_concentration"] = entries

    # --- Geographic Revenue ---
    entries = _map_geographic_revenue(df)
    if entries:
        supplements["geographic_revenue"] = entries

    # --- Inventory Composition ---
    inv_entries = _map_inventory_composition(df)
    if inv_entries:
        supplements["inventory_composition"] = inv_entries

    # --- Purchase Obligations ---
    po_entries = _map_purchase_obligations(df)
    if po_entries:
        supplements["purchase_obligations"] = po_entries

    return {
        "filing": metadata,
        "data": supplements,
        "xbrl_available": True,
    }
