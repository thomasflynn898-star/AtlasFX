#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    parser = argparse.ArgumentParser(description="AtlasFX Paper Trading Agent")
    parser.add_argument("--scan-once", action="store_true", help="Run single scan and exit")
    parser.add_argument("--status", action="store_true", help="Show account status")
    args = parser.parse_args()

    if args.status:
        from config.settings import settings
        from broker.oanda import OANDABroker
        from logs.logger import configure_logging
        configure_logging(log_level="WARNING")
        broker = OANDABroker(api_key=settings.oanda_api_key,
            account_id=settings.oanda_account_id,
            environment=settings.oanda_environment.value)
        print("\n── AtlasFX Status ────────────────────────────────────")
        if broker.test_connection():
            a = broker.get_account()
            print(f"  OANDA    : ✓ Connected")
            print(f"  Balance  : {a.balance:,.2f} {a.currency}")
            print(f"  NAV      : {a.nav:,.2f} {a.currency}")
            print(f"  Trades   : {a.open_trade_count} open")
            print("\n  Live prices:")
            for inst in ["EUR_USD","GBP_USD","XAU_USD"]:
                try:
                    p = broker.get_price(inst)
                    print(f"    {inst:<10} {p.mid:.5f}")
                except: pass
        else:
            print("  OANDA    : ✗ Not connected")
        print()
        return

    from paper_trading.agent import PaperTradingAgent
    agent = PaperTradingAgent()

    if args.scan_once:
        print("\nRunning single scan...")
        result = agent.run_single_scan()
        print(f"\n── Scan Result ───────────────────────────────────────")
        print(f"  Scans run      : {result['scan_count']}")
        print(f"  Open positions : {result['open_positions']}")
        print(f"  Risk halted    : {result['risk_halted']}")
        if result['positions']:
            print(f"  Positions      : {', '.join(result['positions'])}")
        print()
    else:
        agent.start()

if __name__ == "__main__":
    main()
