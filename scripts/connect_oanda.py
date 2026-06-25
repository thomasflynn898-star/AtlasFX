#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logs.logger import configure_logging, get_logger
configure_logging(log_level="INFO", environment="development")
log = get_logger("connect_oanda")

def get_broker():
    from config.settings import settings
    from broker.oanda import OANDABroker
    if not settings.oanda_api_key:
        print("\n✗ OANDA_API_KEY not set in .env")
        print("  1. Open a free practice account at https://www.oanda.com")
        print("  2. My Account → Manage API Access → Generate Token")
        print("  3. Add to .env:\n")
        print("     OANDA_API_KEY=your-token")
        print("     OANDA_ACCOUNT_ID=001-004-XXXXXXX-001")
        print("     OANDA_ENVIRONMENT=practice\n")
        sys.exit(1)
    return OANDABroker(api_key=settings.oanda_api_key,
        account_id=settings.oanda_account_id,
        environment=settings.oanda_environment.value)

def show_account(broker):
    print("\n── Account ───────────────────────────────────────────")
    a = broker.get_account()
    print(f"  Account ID  : {a.account_id}")
    print(f"  Currency    : {a.currency}")
    print(f"  Balance     : {a.balance:,.2f}")
    print(f"  NAV         : {a.nav:,.2f}")
    print(f"  Open trades : {a.open_trade_count}")

def show_prices(broker):
    print("\n── Live Prices ───────────────────────────────────────")
    for inst in ["EUR_USD","GBP_USD","USD_JPY","XAU_USD"]:
        try:
            p = broker.get_price(inst)
            pip = 0.01 if ("JPY" in inst or "XAU" in inst) else 0.0001
            spread = p.spread / pip
            print(f"  {inst:<10} Bid:{p.bid:.5f}  Ask:{p.ask:.5f}  Spread:{spread:.1f}p")
        except Exception as e:
            print(f"  {inst:<10} Error: {e}")

def fetch_candles(broker, instrument, granularity, count):
    print(f"\n── Candles: {instrument} {granularity} ({count} bars) ───────────────")
    try:
        df = broker.get_candles_as_dataframe(instrument, granularity, int(count))
        if df.empty:
            print("  No data returned"); return
        print(f"  Bars: {len(df)}  |  From: {df.index[0]}  |  To: {df.index[-1]}")
        print(f"  Last close: {df["Close"].iloc[-1]:.5f}")
        import pandas as pd
        from config.settings import settings
        path = settings.data_historical_path / instrument / f"{granularity}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            combined.to_parquet(path)
            print(f"  ✓ Merged: {len(combined)} total bars saved")
        else:
            df.to_parquet(path)
            print(f"  ✓ Saved to {path}")
    except Exception as e:
        print(f"  ✗ Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="AtlasFX OANDA Connection Tool")
    parser.add_argument("--prices", action="store_true")
    parser.add_argument("--fetch-candles", nargs=3, metavar=("INST","TF","COUNT"))
    parser.add_argument("--download-all", action="store_true")
    args = parser.parse_args()

    broker = get_broker()
    print("\n── Connection Test ───────────────────────────────────")
    if broker.test_connection():
        print("  ✓ Connected to OANDA API")
    else:
        print("  ✗ Connection failed"); sys.exit(1)

    show_account(broker)
    show_prices(broker)

    if args.fetch_candles:
        fetch_candles(broker, *args.fetch_candles)

    if args.download_all:
        print("\n── Downloading H4 + H1 + D for all instruments ──────")
        for inst in ["EUR_USD","GBP_USD","USD_JPY","XAU_USD"]:
            for tf, count in [("H4",5000),("H1",2000),("D",5000)]:
                print(f"  {inst} {tf}...")
                fetch_candles(broker, inst, tf, count)

    print("\n✓ Done. Ready for Phase 5.\n")

if __name__ == "__main__":
    main()
