from __future__ import annotations

import pytest

from sec_analyzer import engine, extract, extract_xbrl
from sec_analyzer.presets import SupplyChain


SUPPLY_CHAIN_FIELDS = {
    "suppliers",
    "customers",
    "single_source_dependencies",
    "geographic_concentration",
    "capacity_constraints",
    "supply_chain_risks",
    "revenue_concentration",
    "geographic_revenue",
    "purchase_obligations",
    "market_risk_disclosures",
    "inventory_composition",
}

XBRL_FIELDS = {
    "revenue_concentration",
    "geographic_revenue",
    "inventory_composition",
    "purchase_obligations",
}

# A small, fixed filing-like passage. The weekly live health-check feeds this to
# the real OpenRouter extraction path (model resolution, structured output, the
# API key) WITHOUT a live SEC fetch — SEC EDGAR returns HTTP 403 to shared
# CI/datacenter IPs, so a real SEC call from GitHub Actions is unreliable and
# would cry wolf. This fixture-driven check stays reliable on CI and goes red on
# real model/slug/structured-output drift. See docs/DECISIONS.md (2026-06-08,
# "Weekly live health-check is OpenRouter-only").
_FIXTURE_FILING = """\
ITEM 1. BUSINESS — SUPPLY CHAIN

The Company relies on Taiwan Semiconductor Manufacturing Company (TSMC) as its
primary foundry for advanced semiconductors, and purchases memory components
from SK Hynix Inc. and Micron Technology, Inc. Two large cloud-service customers
together accounted for a significant portion of revenue. Manufacturing and final
assembly are concentrated in Taiwan. The Company has unconditional purchase
obligations of approximately $5.0 billion.
"""


def _assert_filing_metadata(filing):
    assert filing["form"]
    assert filing["filing_date"]
    assert filing["accession_number"]
    assert filing["filing_url"]


@pytest.mark.live
def test_live_openrouter_extraction_shape():
    """Weekly live health-check: a real OpenRouter extraction on a fixture
    filing (no live SEC). Goes red on model/slug/structured-output drift."""
    from dotenv import load_dotenv

    load_dotenv()  # local .env; in CI the workflow injects OPENROUTER_API_KEY
    result = engine._extract_with_llm(
        filing_text=_FIXTURE_FILING,
        preset_cls=SupplyChain,
        company_name="Example Corp",
    )
    data = result.model_dump()

    assert SUPPLY_CHAIN_FIELDS.issubset(data)
    for field in SUPPLY_CHAIN_FIELDS:
        assert isinstance(data[field], list)
    # The fixture names suppliers explicitly, so a healthy model must extract at
    # least one — this catches a model that "succeeds" but returns nothing.
    assert len(data["suppliers"]) >= 1


@pytest.mark.live
@pytest.mark.sec
def test_live_sec_supply_chain_extract_shape():
    """On-demand full live check (real SEC + OpenRouter). Excluded from the
    weekly CI cron because SEC blocks CI IPs; run locally with `pytest -m sec`."""
    result = extract("NVDA", SupplyChain)

    assert set(result) == {"filing", "data"}
    _assert_filing_metadata(result["filing"])

    data = result["data"]
    assert SUPPLY_CHAIN_FIELDS.issubset(data)
    for field in SUPPLY_CHAIN_FIELDS:
        assert isinstance(data[field], list)


@pytest.mark.live
@pytest.mark.sec
def test_live_sec_xbrl_extract_shape():
    """On-demand full live check (real SEC). Excluded from the weekly CI cron;
    run locally with `pytest -m sec`."""
    result = extract_xbrl("NVDA")

    assert set(result) == {"filing", "data", "xbrl_available"}
    _assert_filing_metadata(result["filing"])
    assert isinstance(result["xbrl_available"], bool)
    assert isinstance(result["data"], dict)
    assert set(result["data"]).issubset(XBRL_FIELDS)
    for entries in result["data"].values():
        assert isinstance(entries, list)
