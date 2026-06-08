from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from sec_analyzer import engine


CURRENT = "2026-01-25"
OLD = "2025-01-26"


class FakeFiling:
    def __init__(self, xbrl_value) -> None:
        self._xbrl_value = xbrl_value

    def xbrl(self):
        if isinstance(self._xbrl_value, Exception):
            raise self._xbrl_value
        return self._xbrl_value


class FakeFacts:
    def __init__(self, dataframe) -> None:
        self._dataframe = dataframe

    def to_dataframe(self):
        if isinstance(self._dataframe, Exception):
            raise self._dataframe
        return self._dataframe


def _metadata():
    return {
        "form": "10-K",
        "filing_date": "2026-02-25",
        "accession_number": "0001045810-26-000021",
        "filing_url": "https://www.sec.gov/Archives/example",
    }


def _patch_xbrl_filing(monkeypatch, xbrl_value):
    monkeypatch.setattr(
        engine,
        "_get_filing",
        MagicMock(return_value=(FakeFiling(xbrl_value), _metadata(), "NVIDIA")),
    )


def _fact(
    concept: str,
    numeric_value: float | None,
    *,
    period_end: str | None = None,
    period_instant: str | None = None,
    period_type: str = "duration",
    geo: str | None = None,
    customer: str | None = None,
    benchmark: str | None = None,
    is_dimensioned: bool | None = None,
):
    dimensioned = bool(geo or customer or benchmark)
    if is_dimensioned is not None:
        dimensioned = is_dimensioned
    return {
        "concept": concept,
        "value": None if numeric_value is None else str(numeric_value),
        "numeric_value": numeric_value,
        "period_end": period_end,
        "period_instant": period_instant,
        "period_type": period_type,
        "is_dimensioned": dimensioned,
        "dimension": None,
        "member": None,
        engine._XBRL_GEO_AXIS_COL: geo,
        engine._XBRL_MAJOR_CUSTOMERS_COL: customer,
        engine._XBRL_BENCHMARK_COL: benchmark,
    }


def _facts_df(rows, *, string_dtype: bool = False):
    df = pd.DataFrame(rows)
    expected_columns = {
        "concept",
        "value",
        "numeric_value",
        "period_end",
        "period_instant",
        "period_type",
        "is_dimensioned",
        "dimension",
        "member",
        engine._XBRL_GEO_AXIS_COL,
        engine._XBRL_MAJOR_CUSTOMERS_COL,
        engine._XBRL_BENCHMARK_COL,
    }
    for column in expected_columns:
        if column not in df.columns:
            df[column] = None
    if string_dtype:
        for column in expected_columns - {"numeric_value", "is_dimensioned"}:
            df[column] = df[column].astype("string")
    return df


def _run_extract_xbrl(monkeypatch, df):
    _patch_xbrl_filing(monkeypatch, SimpleNamespace(facts=FakeFacts(df)))
    return engine.extract_xbrl("NVDA")


def test_extract_xbrl_maps_four_categories_and_filters_current_facts(monkeypatch):
    rows = [
        # Old-period inventory rows are deliberately first to catch order-based
        # denominator bugs.
        _fact(
            "us-gaap:InventoryNet",
            1_000_000_000,
            period_instant=OLD,
            period_type="instant",
        ),
        _fact(
            "us-gaap:InventoryRawMaterialsAndSuppliesNetOfReserves",
            900_000_000,
            period_instant=OLD,
            period_type="instant",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.10,
            period_end=OLD,
            customer="nvda:OldCustomerMember",
            benchmark="us-gaap:SalesRevenueNetMember",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.25,
            period_end=CURRENT,
            customer="nvda:CustomerOneMember",
            benchmark="us-gaap:SalesRevenueNetMember",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.33,
            period_end=CURRENT,
            customer="nvda:CustomerOneMember",
            benchmark="us-gaap:SalesRevenueNetMember",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.50,
            period_end=CURRENT,
            customer="nvda:CustomerTwoMember",
            benchmark="us-gaap:AccountsReceivableMember",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            None,
            period_end=CURRENT,
            customer="nvda:NullCustomerMember",
            benchmark="us-gaap:SalesRevenueNetMember",
        ),
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.40,
            period_end=CURRENT,
            customer="nvda:MiddleEastMember",
            benchmark="us-gaap:RevenueMember",
        ),
        # NVDA-like leak: current revenue benchmark customer-axis member that
        # also carries a geo cell. It is not in the geo-member set, so the
        # geo-cell guard must exclude it.
        _fact(
            "us-gaap:ConcentrationRiskPercentage1",
            0.76,
            period_end=CURRENT,
            geo="country:TW",
            customer="nvda:UnitedStatesAndEuropeBasedEndCustomersMember",
            benchmark="us-gaap:SalesRevenueNetMember",
        ),
        _fact(
            "us-gaap:Revenues",
            1_000_000_000,
            period_end=CURRENT,
            period_type="duration",
            is_dimensioned=False,
        ),
        _fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            600_000_000,
            period_end=CURRENT,
            geo="country:US",
        ),
        _fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            650_000_000,
            period_end=CURRENT,
            geo="country:US",
        ),
        _fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            200_000_000,
            period_end=CURRENT,
            geo="nvda:MiddleEastMember",
        ),
        _fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            None,
            period_end=CURRENT,
            geo="country:CN",
        ),
        _fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            100_000_000,
            period_end=OLD,
            geo="country:JP",
        ),
        _fact(
            "us-gaap:InventoryNet",
            100_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:InventoryRawMaterialsAndSuppliesNetOfReserves",
            25_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:InventoryWorkInProcessNetOfReserves",
            30_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:InventoryFinishedGoodsNetOfReserves",
            45_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationBalanceSheetAmount",
            227_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationFirstAnniversary",
            10_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationSecondAnniversary",
            20_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationThirdAnniversary",
            30_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationFourthAnniversary",
            40_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationFifthAnniversary",
            50_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationAfterFiveYears",
            60_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
        _fact(
            "us-gaap:UnrecordedUnconditionalPurchaseObligationTextBlock",
            999_000_000,
            period_instant=CURRENT,
            period_type="instant",
        ),
    ]

    result = _run_extract_xbrl(monkeypatch, _facts_df(rows, string_dtype=True))

    assert result["xbrl_available"] is True
    data = result["data"]
    assert set(data) == {
        "revenue_concentration",
        "geographic_revenue",
        "inventory_composition",
        "purchase_obligations",
    }

    revenue_concentration = data["revenue_concentration"]
    assert revenue_concentration == [
        {
            "entity": "Customer One",
            "revenue_pct": 25.0,
            "source": "xbrl",
            "end_date": CURRENT,
        }
    ]
    excluded_entities = {
        "Customer Two",
        "Null Customer",
        "Old Customer",
        "Middle East",
        "United States And Europe Based End Customers",
    }
    assert excluded_entities.isdisjoint(
        {entry["entity"] for entry in revenue_concentration}
    )

    geographic_revenue = {
        entry["region"]: entry for entry in data["geographic_revenue"]
    }
    assert set(geographic_revenue) == {"United States", "Middle East"}
    assert geographic_revenue["United States"]["revenue_pct"] == 60.0
    assert geographic_revenue["United States"]["revenue_amount"] == "$600M"
    assert geographic_revenue["Middle East"]["revenue_pct"] == 20.0

    inventory = {
        entry["category"]: entry for entry in data["inventory_composition"]
    }
    assert inventory["raw_materials"]["amount"] == "$25M"
    assert inventory["raw_materials"]["pct_of_total"] == 25.0
    assert inventory["work_in_progress"]["pct_of_total"] == 30.0
    assert inventory["finished_goods"]["pct_of_total"] == 45.0

    timeframes = {
        entry["timeframe"] for entry in data["purchase_obligations"]
    }
    assert timeframes == {
        "total",
        "year 1",
        "year 2",
        "year 3",
        "year 4",
        "year 5",
        "after year 5",
    }


def test_extract_xbrl_coalesces_period_end_and_period_instant(monkeypatch):
    df = _facts_df(
        [
            _fact(
                "us-gaap:ConcentrationRiskPercentage1",
                0.42,
                period_end=None,
                period_instant=CURRENT,
                customer="nvda:CustomerOneMember",
                benchmark="us-gaap:SalesRevenueNetMember",
            )
        ]
    )

    result = _run_extract_xbrl(monkeypatch, df)

    assert result["data"]["revenue_concentration"][0]["end_date"] == CURRENT


@pytest.mark.parametrize(
    "xbrl_value",
    [
        RuntimeError("xbrl unavailable"),
        None,
        SimpleNamespace(facts=FakeFacts(pd.DataFrame())),
        SimpleNamespace(facts=FakeFacts(RuntimeError("facts unavailable"))),
    ],
)
def test_extract_xbrl_degrades_when_xbrl_is_unavailable(monkeypatch, xbrl_value):
    _patch_xbrl_filing(monkeypatch, xbrl_value)

    result = engine.extract_xbrl("NVDA")

    assert result == {
        "filing": _metadata(),
        "data": {},
        "xbrl_available": False,
    }


def test_extract_xbrl_available_with_no_target_concepts_returns_empty_data(
    monkeypatch,
):
    df = _facts_df(
        [
            _fact(
                "dei:EntityRegistrantName",
                1,
                period_end=CURRENT,
                period_type="duration",
                is_dimensioned=False,
            )
        ]
    )

    result = _run_extract_xbrl(monkeypatch, df)

    assert result == {
        "filing": _metadata(),
        "data": {},
        "xbrl_available": True,
    }
