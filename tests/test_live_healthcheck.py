from __future__ import annotations

import pytest

from sec_analyzer import extract, extract_xbrl
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


def _assert_filing_metadata(filing):
    assert filing["form"]
    assert filing["filing_date"]
    assert filing["accession_number"]
    assert filing["filing_url"]


@pytest.mark.live
def test_live_supply_chain_extract_shape():
    result = extract("NVDA", SupplyChain)

    assert set(result) == {"filing", "data"}
    _assert_filing_metadata(result["filing"])

    data = result["data"]
    assert SUPPLY_CHAIN_FIELDS.issubset(data)
    for field in SUPPLY_CHAIN_FIELDS:
        assert isinstance(data[field], list)


@pytest.mark.live
def test_live_xbrl_extract_shape():
    result = extract_xbrl("NVDA")

    assert set(result) == {"filing", "data", "xbrl_available"}
    _assert_filing_metadata(result["filing"])
    assert isinstance(result["xbrl_available"], bool)
    assert isinstance(result["data"], dict)
    assert set(result["data"]).issubset(XBRL_FIELDS)
    for entries in result["data"].values():
        assert isinstance(entries, list)
