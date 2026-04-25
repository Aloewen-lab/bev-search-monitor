"""Thin entrypoint for cron / GitHub Actions.

Delegates to fetcher.py — kept as a separate file so the update command stays
stable even if fetcher internals change.

    python update.py
    python update.py --markets DE,UK
    python update.py --dry-run
"""

import argparse
from fetcher import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--markets", help="Comma-separated market codes (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(
        markets=args.markets.split(",") if args.markets else None,
        dry_run=args.dry_run,
    )
