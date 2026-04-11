"""CLI entry point for sec-analyzer."""

import argparse
import json
import sys


_PRESET_MAP = {
    "supply-chain": "sec_analyzer.presets.supply_chain:SupplyChain",
}


def _load_preset(name: str):
    """Load a preset class by name or module:ClassName path."""
    import importlib

    if ":" in name:
        # Custom preset: "my_package.module:ClassName"
        module_path, class_name = name.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            print(f"Cannot import module '{module_path}': {e}", file=sys.stderr)
            sys.exit(1)
        cls = getattr(mod, class_name, None)
        if cls is None:
            print(f"Class '{class_name}' not found in module '{module_path}'", file=sys.stderr)
            sys.exit(1)
        return cls

    if name not in _PRESET_MAP:
        print(f"Unknown preset: {name}", file=sys.stderr)
        print(f"Available presets: {', '.join(_PRESET_MAP)}", file=sys.stderr)
        print("Or use module:ClassName for custom presets (e.g., my_package.presets:MyPreset)", file=sys.stderr)
        sys.exit(1)

    module_path, class_name = _PRESET_MAP[name].rsplit(":", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def main():
    parser = argparse.ArgumentParser(
        description="Extract structured data from SEC filings"
    )
    parser.add_argument("symbol", help="Ticker symbol (e.g., NVDA, AAPL, TSM)")
    parser.add_argument(
        "--preset", default="supply-chain",
        help=f"Built-in preset ({', '.join(_PRESET_MAP)}) or custom module:ClassName path",
    )
    parser.add_argument("--form", default="10-K", help="Filing form type (default: 10-K)")
    parser.add_argument("--filing-date", default=None, help="Specific filing date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", dest="compact", help="Compact JSON output")

    args = parser.parse_args()

    preset_cls = _load_preset(args.preset)

    from .engine import extract

    try:
        result = extract(
            symbol=args.symbol,
            preset=preset_cls,
            form=args.form,
            filing_date=args.filing_date,
        )
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    indent = None if args.compact else 2
    print(json.dumps(result, indent=indent, default=str))


if __name__ == "__main__":
    main()
