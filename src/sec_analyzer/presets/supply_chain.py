"""Supply chain intelligence preset for SEC filings.

Extracts suppliers, customers, single-source dependencies, geographic
concentration, capacity constraints, supply chain risks, revenue concentration,
geographic revenue, purchase obligations, market risk disclosures, and
inventory composition from 10-K/10-Q/20-F filings.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field


class SupplierEntry(BaseModel):
    entity: str = Field(description="Name of the supplier company. Use exact name from the filing.")
    relationship: str = Field(default="", description="Nature of the supply relationship (e.g., 'sole source supplier', 'key component vendor').")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing that supports this supplier relationship.")


class CustomerEntry(BaseModel):
    entity: str = Field(description="Name of the customer company. Use exact name from the filing.")
    relationship: str = Field(default="", description="Nature of the customer relationship (e.g., 'major customer', 'accounted for 35% of revenue').")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing that supports this customer relationship.")


class SingleSourceEntry(BaseModel):
    component: str = Field(default="", description="Component or material with single-source dependency (e.g., 'DRAM memory chips').")
    supplier: str = Field(description="Name of the sole-source or single-source supplier.")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing describing this dependency.")


class GeographicEntry(BaseModel):
    location: str = Field(description="Country or region name (e.g., 'Taiwan', 'South Korea').")
    activity: str = Field(default="", description="Type of activity at this location (e.g., 'manufacturing', 'assembly').")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing describing geographic concentration.")


class CapacityConstraintEntry(BaseModel):
    constraint: str = Field(description="Type of capacity constraint (e.g., 'extended lead times', 'production capacity limitation').")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing describing the constraint.")


class SupplyChainRiskEntry(BaseModel):
    risk: str = Field(description="Type of supply chain risk (e.g., 'tariff impact', 'raw material shortage').")
    context: str = Field(default="", description="Brief relevant excerpt (1-3 sentences) from the filing describing this risk.")


class RevenueConcentrationEntry(BaseModel):
    entity: str = Field(description="Customer or segment name from filing.")
    revenue_pct: float | None = Field(default=None, description="% of total revenue (e.g., 35.2).")
    revenue_amount: str = Field(default="", description="Amount if disclosed (e.g., '$5.2 billion').")
    context: str = Field(default="", description="1-3 sentences from Notes.")


class GeographicRevenueEntry(BaseModel):
    region: str = Field(description="Country or region (e.g., 'United States', 'China').")
    revenue_pct: float | None = Field(default=None, description="% of total revenue.")
    revenue_amount: str = Field(default="", description="Amount if disclosed.")
    context: str = Field(default="", description="1-3 sentences from Notes.")


class PurchaseObligationEntry(BaseModel):
    counterparty: str = Field(default="", description="Supplier name if disclosed.")
    obligation_type: str = Field(description="Type (e.g., 'inventory commitment', 'capacity reservation').")
    amount: str = Field(default="", description="Dollar amount (e.g., '$2.5 billion').")
    timeframe: str = Field(default="", description="Duration (e.g., 'through fiscal 2027').")
    context: str = Field(default="", description="1-3 sentences from Notes.")


class MarketRiskEntry(BaseModel):
    risk_type: Literal["commodity", "fx", "interest_rate"] = Field(description="Type: 'commodity', 'fx', or 'interest_rate'.")
    exposure: str = Field(default="", description="Specific exposure (e.g., 'gold price', 'EUR/USD').")
    sensitivity: str = Field(default="", description="Quantitative impact if disclosed (e.g., '10% increase = $50M COGS impact').")
    hedging: str = Field(default="", description="Hedging strategy if disclosed.")
    context: str = Field(default="", description="1-3 sentences from filing.")


class InventoryCompositionEntry(BaseModel):
    category: Literal["raw_materials", "work_in_progress", "finished_goods"] = Field(description="Category: 'raw_materials', 'work_in_progress', or 'finished_goods'.")
    amount: str = Field(default="", description="Dollar amount if disclosed (e.g., '$1.2 billion').")
    pct_of_total: float | None = Field(default=None, description="% of total inventory.")
    context: str = Field(default="", description="1-3 sentences from Notes (valuation, aging, obsolescence).")


class SupplyChain(BaseModel):
    """Supply chain intelligence extraction from SEC filings."""

    __prompt__: ClassVar[str] = """\
You are a financial analyst extracting supply chain intelligence from SEC filings.
Extract entities and relationships exactly as stated in the filing text.

The filing text below is the complete SEC filing in markdown format.
Identify relevant sections by their natural headings:
- Item 1 (Business): suppliers, customers, single-source dependencies
- Item 1A (Risk Factors): supply chain risks, geographic concentration
- Item 7 (MD&A): capacity constraints, operating discussion
- Item 7A (Market Risk): commodity/FX/interest rate exposures
- Item 8 Notes: revenue segments, inventory, commitments, concentration
For 20-F filings, look for equivalent items (Item 4, 3D, 5, 11, 18/19).

Rules:
1. Use exact company names from the filing — do not paraphrase or invent.
2. For context fields, copy 1-3 relevant sentences verbatim from the filing.
3. If a category has no relevant data, return an empty list.
4. Do NOT extract the filing company itself as its own supplier or customer.
5. Focus on factual supply chain relationships — skip generic boilerplate.
6. De facto single-source: If a supplier is described as the PRIMARY or ONLY provider
   for a critical component category and NO alternative supplier is mentioned for that
   same category, classify it as single_source_dependencies.
7. Customer extraction: Look for revenue concentration disclosures, named buyers,
   and "accounted for X% of revenue" language.
8. Relationship specificity: Use precise descriptions such as "sole foundry for
   leading-edge GPUs", "memory supplier (HBM)", "anchor customer >10% revenue".
9. Only infer relationships where the filing text provides contextual support.
10. Revenue concentration: From Notes, extract customers/segments with specific % of
    revenue. Include exact percentage as revenue_pct.
11. Geographic revenue: From Notes, extract revenue by country/region with exact
    percentages. Use standardized country names.
12. Purchase obligations: From Notes (Commitments and Contingencies), extract purchase
    commitments, capacity reservations, take-or-pay contracts.
13. Market risk disclosures: From Item 7A, extract commodity/FX/interest rate exposures.
    Classify risk_type as "commodity", "fx", or "interest_rate".
14. Inventory composition: From Notes, extract raw materials, work-in-progress, and
    finished goods amounts and percentages.

Filing company: {company_name}

Extract all supply chain entities from this SEC filing text:

{filing_text}
"""

    suppliers: list[SupplierEntry] = Field(default_factory=list, description="Companies that supply products, materials, or services to the filing company.")
    customers: list[CustomerEntry] = Field(default_factory=list, description="Companies that purchase products or services from the filing company.")
    single_source_dependencies: list[SingleSourceEntry] = Field(default_factory=list, description="Components with sole-source or single-source supplier dependencies.")
    geographic_concentration: list[GeographicEntry] = Field(default_factory=list, description="Locations where manufacturing, production, or sourcing is concentrated.")
    capacity_constraints: list[CapacityConstraintEntry] = Field(default_factory=list, description="Production capacity limitations, extended lead times, or backlogs.")
    supply_chain_risks: list[SupplyChainRiskEntry] = Field(default_factory=list, description="Supply disruption risks including tariffs, shortages, geopolitical risks.")
    revenue_concentration: list[RevenueConcentrationEntry] = Field(default_factory=list, description="Customer/segment revenue concentration from Notes.")
    geographic_revenue: list[GeographicRevenueEntry] = Field(default_factory=list, description="Revenue breakdown by country/region from Notes.")
    purchase_obligations: list[PurchaseObligationEntry] = Field(default_factory=list, description="Purchase commitments, capacity reservations from Notes.")
    market_risk_disclosures: list[MarketRiskEntry] = Field(default_factory=list, description="Market risk exposures from Item 7A.")
    inventory_composition: list[InventoryCompositionEntry] = Field(default_factory=list, description="Inventory breakdown from Notes.")
