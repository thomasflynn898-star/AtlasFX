#!/usr/bin/env python3
"""
scripts/download_data.py
────────────────────────
CLI script to download historical FX data.

Usage:
    python scripts/download_data.py --instrument EUR_USD --timeframe H1 --years 3
    python scripts/download_data.py --all --timeframes H1 H4 D --years 4
    python scripts/download_data.py --list-instruments
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import INSTRUMENTS, TIMEFRAMES
from data.downloader import YFINANCE_SYMBOL_MAP, HistoricalDownloader
from logs.logger import configure_logging, get_logger


def main() -> None:
    configure_logging(log_level="INFO", environment="development")
    log = get_logger("download_data")

    parser = argparse.ArgumentParser(
        description="AtlasFX historical data downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/download_data.py --instrument EUR_USD --timeframe H1 --years 3
  python scripts/download_data.py --all --timeframes H1 H4 D --years 4
  python scripts/download_data.py --list-instruments
        """,
    )
    parser.add_argument("--instrument", type=str, help="Instrument e.g. EUR_USD")
    parser.add_argument("--timeframe", type=str, help="Timeframe e.g. H1")
    parser.add_argument(
        "--timeframes", nargs="+", default=["H1", "H4", "D"],
        help="Multiple timeframes for --all mode",
    )
    parser.add_argument("--years", type=int, default=3, help="Years of history to download")
    parser.add_argument("--all", action="store_true", help="Download all configured instruments")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass cache")
    parser.add_argument("--list-instruments", action="store_true", help="List available instruments")
    args = parser.parse_args()

    if args.list_instruments:
        print("\nAvailable instruments (yfinance mapped):")
        for inst, ticker in YFINANCE_SYMBOL_MAP.items():
            print(f"  {inst:15} → {ticker}")
        print(f"\nAvailable timeframes: {', '.join(TIMEFRAMES)}")
        print()
        return

    dl = HistoricalDownloader()

    if args.all:
        log.info("bulk_download_start", timeframes=args.timeframes, years=args.years)
        results = dl.download_all_configured(
            timeframes=args.timeframes,
            years=args.years,
        )
        print("\n── Download Summary ──────────────────────────")
        for instrument, tfs in results.items():
            for tf, df in tfs.items():
                status = f"{len(df):,} bars" if not df.empty else "FAILED"
                print(f"  {instrument:15} {tf:5} {status}")
        print()

    elif args.instrument and args.timeframe:
        from datetime import datetime, timedelta
        start = (datetime.utcnow() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")
        log.info(
            "single_download_start",
            instrument=args.instrument,
            timeframe=args.timeframe,
            start=start,
        )
        try:
            df = dl.download(
                args.instrument,
                args.timeframe,
                start=start,
                force_refresh=args.force_refresh,
            )
            print(f"\n✓ Downloaded {len(df):,} bars for {args.instrument} {args.timeframe}")
            print(f"  From: {df.index[0]}")
            print(f"  To:   {df.index[-1]}")
            print(f"  Saved to: {dl._parquet_path(args.instrument, args.timeframe)}\n")
        except Exception as e:
            log.error("download_failed", error=str(e))
            print(f"\n✗ Download failed: {e}\n")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
