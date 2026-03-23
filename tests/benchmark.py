"""SEC-Analyzer extraction quality benchmark.

Runs 3 scenarios across 10 diverse tickers:
1. LLM extraction consistency (3 runs per ticker)
2. XBRL data availability
3. LLM vs XBRL quantitative comparison

Usage:
    python tests/benchmark.py                    # All scenarios
    python tests/benchmark.py --scenario 1       # Consistency only
    python tests/benchmark.py --scenario 2       # XBRL only
    python tests/benchmark.py --scenario 3       # Comparison only
    python tests/benchmark.py --tickers NVDA,AAPL  # Specific tickers
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sec_analyzer import extract, extract_xbrl
from sec_analyzer.presets import SupplyChain

RESULTS_DIR = Path(__file__).parent / "results"

TICKERS = {
    "large_tech": ["NVDA", "AAPL"],
    "manufacturing": ["F", "CAT"],
    "foreign_20f": ["TSM", "ASML"],
    "non_manufacturing": ["CRWD", "JPM"],
    "mid_cap": ["PLTR", "SMCI"],
}

ALL_TICKERS = [t for group in TICKERS.values() for t in group]

SUPPLY_CHAIN_FIELDS = [
    "suppliers", "customers", "single_source_dependencies",
    "geographic_concentration", "capacity_constraints", "supply_chain_risks",
    "revenue_concentration", "geographic_revenue", "purchase_obligations",
    "market_risk_disclosures", "inventory_composition",
]

XBRL_FIELDS = ["revenue_concentration", "geographic_revenue",
               "inventory_composition", "purchase_obligations"]


def _save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _run_single_extract(ticker, run_id):
    """Run a single LLM extraction. Returns (ticker, run_id, result_or_error)."""
    try:
        result = extract(ticker, preset=SupplyChain)
        return ticker, run_id, result
    except Exception as e:
        return ticker, run_id, {"error": str(e)}


def scenario_1_consistency(tickers, runs=3, workers=5):
    """Scenario 1: LLM extraction consistency."""
    print(f"\n{'='*60}")
    print(f"Scenario 1: LLM Consistency ({len(tickers)} tickers × {runs} runs)")
    print(f"{'='*60}")

    out_dir = RESULTS_DIR / "consistency"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build all tasks
    tasks = [(t, r) for t in tickers for r in range(1, runs + 1)]

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_single_extract, t, r): (t, r) for t, r in tasks}
        for fut in as_completed(futures):
            ticker, run_id, result = fut.result()
            if ticker not in results:
                results[ticker] = {}
            results[ticker][run_id] = result

            if "error" in result:
                print(f"  {ticker} run{run_id}: ERROR - {result['error'][:60]}")
            else:
                counts = {f: len(result["data"].get(f, [])) for f in SUPPLY_CHAIN_FIELDS}
                total = sum(counts.values())
                print(f"  {ticker} run{run_id}: {total} total items")

            _save_json(result, out_dir / f"{ticker}_run{run_id}.json")

    # Compute consistency stats
    stats = {}
    for ticker in tickers:
        ticker_runs = results.get(ticker, {})
        stats[ticker] = {}
        for field in SUPPLY_CHAIN_FIELDS:
            counts = []
            for r in range(1, runs + 1):
                run_data = ticker_runs.get(r, {})
                if "error" not in run_data:
                    counts.append(len(run_data.get("data", {}).get(field, [])))
            if counts:
                mean = sum(counts) / len(counts)
                variance = sum((c - mean) ** 2 for c in counts) / len(counts)
                std = variance ** 0.5
                cv = std / mean if mean > 0 else 0
                stats[ticker][field] = {
                    "counts": counts, "min": min(counts), "max": max(counts),
                    "mean": round(mean, 2), "std": round(std, 2), "cv": round(cv, 3),
                }
            else:
                stats[ticker][field] = {"counts": [], "error": "all runs failed"}

    _save_json(stats, RESULTS_DIR / "consistency_stats.json")
    print(f"\nStats saved to {RESULTS_DIR / 'consistency_stats.json'}")
    return stats


def scenario_2_xbrl(tickers, workers=5):
    """Scenario 2: XBRL data availability."""
    print(f"\n{'='*60}")
    print(f"Scenario 2: XBRL Availability ({len(tickers)} tickers)")
    print(f"{'='*60}")

    out_dir = RESULTS_DIR / "xbrl"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _run_xbrl(ticker):
        try:
            return ticker, extract_xbrl(ticker)
        except Exception as e:
            return ticker, {"error": str(e)}

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_xbrl, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker, result = fut.result()
            results[ticker] = result
            if "error" in result:
                print(f"  {ticker}: ERROR - {result['error'][:60]}")
            else:
                available = result.get("xbrl_available", False)
                cats = list(result.get("data", {}).keys())
                print(f"  {ticker}: XBRL={'YES' if available else 'NO'}, categories={cats}")
            _save_json(result, out_dir / f"{ticker}_xbrl.json")

    # Summary
    summary = {}
    for ticker in tickers:
        r = results.get(ticker, {})
        data = r.get("data", {})
        summary[ticker] = {
            "xbrl_available": r.get("xbrl_available", False),
            **{f: f in data for f in XBRL_FIELDS},
        }

    _save_json(summary, RESULTS_DIR / "xbrl_availability.json")
    print(f"\nSummary saved to {RESULTS_DIR / 'xbrl_availability.json'}")
    return summary


def scenario_3_comparison(tickers, workers=5):
    """Scenario 3: LLM vs XBRL quantitative comparison."""
    print(f"\n{'='*60}")
    print(f"Scenario 3: LLM vs XBRL Comparison ({len(tickers)} tickers)")
    print(f"{'='*60}")

    out_dir = RESULTS_DIR / "comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _run_both(ticker):
        try:
            llm_result = extract(ticker, preset=SupplyChain)
            xbrl_result = extract_xbrl(ticker)
            return ticker, llm_result, xbrl_result
        except Exception as e:
            return ticker, {"error": str(e)}, {"error": str(e)}

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_both, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker, llm, xbrl = fut.result()

            comparison = {"ticker": ticker}
            for field in XBRL_FIELDS:
                llm_data = llm.get("data", {}).get(field, []) if "error" not in llm else []
                xbrl_data = xbrl.get("data", {}).get(field, []) if "error" not in xbrl else []
                comparison[field] = {
                    "llm_count": len(llm_data),
                    "xbrl_count": len(xbrl_data),
                    "llm_items": llm_data,
                    "xbrl_items": xbrl_data,
                }
                print(f"  {ticker}.{field}: LLM={len(llm_data)}, XBRL={len(xbrl_data)}")

            results[ticker] = comparison
            _save_json(comparison, out_dir / f"{ticker}_comparison.json")

    _save_json(results, RESULTS_DIR / "comparison_summary.json")
    print(f"\nSummary saved to {RESULTS_DIR / 'comparison_summary.json'}")
    return results


def generate_report():
    """Generate final summary report from all scenario results."""
    report = {}

    # Load consistency stats
    stats_path = RESULTS_DIR / "consistency_stats.json"
    if stats_path.exists():
        report["consistency"] = json.loads(stats_path.read_text())

    # Load XBRL availability
    xbrl_path = RESULTS_DIR / "xbrl_availability.json"
    if xbrl_path.exists():
        report["xbrl_availability"] = json.loads(xbrl_path.read_text())

    # Load comparison
    comp_path = RESULTS_DIR / "comparison_summary.json"
    if comp_path.exists():
        raw = json.loads(comp_path.read_text())
        summary = {}
        for ticker, data in raw.items():
            summary[ticker] = {}
            for field in XBRL_FIELDS:
                fd = data.get(field, {})
                summary[ticker][field] = {
                    "llm_count": fd.get("llm_count", 0),
                    "xbrl_count": fd.get("xbrl_count", 0),
                }
        report["llm_vs_xbrl"] = summary

    _save_json(report, RESULTS_DIR / "report.json")
    print(f"\nFinal report: {RESULTS_DIR / 'report.json'}")
    return report


def main():
    parser = argparse.ArgumentParser(description="SEC-Analyzer Benchmark")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3], default=None,
                       help="Run specific scenario (default: all)")
    parser.add_argument("--tickers", type=str, default=None,
                       help="Comma-separated tickers (default: all 10)")
    parser.add_argument("--runs", type=int, default=3, help="Runs per ticker for consistency")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers")
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else ALL_TICKERS
    print(f"Tickers: {tickers}")
    print(f"Workers: {args.workers}")

    start = time.time()

    if args.scenario is None or args.scenario == 1:
        scenario_1_consistency(tickers, runs=args.runs, workers=args.workers)
    if args.scenario is None or args.scenario == 2:
        scenario_2_xbrl(tickers, workers=args.workers)
    if args.scenario is None or args.scenario == 3:
        scenario_3_comparison(tickers, workers=args.workers)

    generate_report()

    elapsed = time.time() - start
    print(f"\nTotal elapsed: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
