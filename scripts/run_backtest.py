#!/usr/bin/env python3
"""
scripts/run_backtest.py
────────────────────────
CLI script to run a backtest and print results.

Usage:
    python scripts/run_backtest.py --strategy london_breakout --instrument EUR_USD
    python scripts/run_backtest.py --strategy london_breakout --instrument EUR_USD --years 4
    python scripts/run_backtest.py --list-strategies
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.engine import BacktestConfig, BacktestEngine
from logs.logger import configure_logging, get_logger
from strategies.strategy_london_breakout import LondonBreakoutStrategy

configure_logging(log_level="WARNING", environment="development")
log = get_logger("run_backtest")

STRATEGIES = {
    "london_breakout": LondonBreakoutStrategy,
}

INSTRUMENTS = ["EUR_USD", "GBP_USD", "USD_JPY", "XAU_USD"]


def print_results(summary: dict) -> None:
    """Print backtest results in a clean format."""
    print("\n" + "═" * 58)
    print(f"  BACKTEST RESULTS — {summary['strategy_id']}")
    print("═" * 58)
    print(f"  Instrument : {summary['instrument']}  ({summary['timeframe']})")
    print(f"  Period     : {summary['period']}")
    print("─" * 58)

    if summary.get("total_trades", 0) == 0:
        print(f"  {summary.get('note', 'No trades.')}")
        print("═" * 58 + "\n")
        return

    print(f"  Initial    : ${summary['initial_balance']:>10,.2f}")
    print(f"  Final      : ${summary['final_balance']:>10,.2f}")
    ret = summary['total_return_pct']
    sign = "+" if ret >= 0 else ""
    print(f"  Return     : {sign}{ret:.2f}%")
    print("─" * 58)
    print(f"  Trades     : {summary['total_trades']}")
    print(f"  Win rate   : {summary['win_rate_pct']:.1f}%  "
          f"({summary['winning_trades']}W / {summary['losing_trades']}L)")
    print(f"  Profit fac : {summary['profit_factor']:.3f}")
    print(f"  Sharpe     : {summary['sharpe_ratio']:.3f}")
    print(f"  Max DD     : {summary['max_drawdown_pct']:.2f}%")
    print(f"  Max cons L : {summary['max_consecutive_losses']}")
    print("─" * 58)
    print(f"  Avg R      : {summary['avg_r_multiple']:.3f}R")
    print(f"  Avg win    : ${summary['avg_win']:,.2f}")
    print(f"  Avg loss   : ${summary['avg_loss']:,.2f}")
    print(f"  Best trade : ${summary['largest_win']:,.2f}")
    print(f"  Worst trade: ${summary['largest_loss']:,.2f}")
    print("─" * 58)
    print(f"  Signals    : {summary['signals_generated']} generated, "
          f"{summary['signals_rejected']} rejected")
    print(f"  Spread cost: ${summary['total_spread_cost']:,.2f}")
    print("═" * 58)
    print()

    # Honest disclaimer
    print("  NOTE: These results are simulated. Spread/slippage are")
    print("  approximations. Past results do not predict future")
    print("  performance. Do not trade live without full validation.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AtlasFX Backtester")
    parser.add_argument("--strategy", type=str, help="Strategy name")
    parser.add_argument("--instrument", type=str, default="EUR_USD")
    parser.add_argument("--timeframe", type=str, default="D")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--risk", type=float, default=0.5,
                        help="Risk per trade %% (max 1.0)")
    parser.add_argument("--spread", type=float, default=1.0,
                        help="Spread in pips")
    parser.add_argument("--list-strategies", action="store_true")
    args = parser.parse_args()

    if args.list_strategies:
        print("\nAvailable strategies:")
        for name, cls in STRATEGIES.items():
            strat = cls()
            print(f"  {name:25} → {strat.METADATA.name}")
        print()
        return

    if not args.strategy:
        parser.print_help()
        return

    if args.strategy not in STRATEGIES:
        print(f"\nUnknown strategy '{args.strategy}'.")
        print(f"Available: {', '.join(STRATEGIES.keys())}\n")
        sys.exit(1)

    from datetime import datetime, timedelta
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")

    config = BacktestConfig(
        instrument=args.instrument,
        timeframe=args.timeframe,
        start_date=start_date,
        end_date=end_date,
        initial_balance=args.balance,
        risk_per_trade_pct=min(args.risk, 1.0),
        spread_pips=args.spread,
        pip_size=0.01 if "JPY" in args.instrument else 0.0001,
    )

    strategy = STRATEGIES[args.strategy]()
    engine = BacktestEngine(config)

    print(f"\nRunning backtest: {args.strategy} on {args.instrument} {args.timeframe}...")
    results = engine.run(strategy)
    print_results(results.summary())


if __name__ == "__main__":
    main()
