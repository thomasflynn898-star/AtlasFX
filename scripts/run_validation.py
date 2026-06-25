#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtesting.engine import BacktestConfig, BacktestEngine
from backtesting.monte_carlo import MonteCarlo, MonteCarloConfig
from backtesting.walk_forward import WalkForwardValidator
from logs.logger import configure_logging, get_logger
from strategies.strategy_macd_ema import MACDEMAStrategy

configure_logging(log_level="WARNING", environment="development")
log = get_logger("run_validation")

PIP_SIZES = {"EUR_USD":0.0001,"GBP_USD":0.0001,"USD_JPY":0.01,"XAU_USD":0.01}

def main():
    parser = argparse.ArgumentParser(description="AtlasFX Validation Suite")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--timeframe", default="D")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--balance", type=float, default=10000.0)
    parser.add_argument("--mc", action="store_true", help="Run Monte Carlo")
    parser.add_argument("--wf", action="store_true", help="Run Walk-Forward")
    parser.add_argument("--mc-sims", type=int, default=10000)
    parser.add_argument("--wf-windows", type=int, default=5)
    args = parser.parse_args()

    if not args.mc and not args.wf:
        parser.print_help()
        return

    from datetime import datetime, timedelta
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=365*args.years)).strftime("%Y-%m-%d")
    pip_size = PIP_SIZES.get(args.instrument, 0.0001)
    strategy = MACDEMAStrategy(pip_size=pip_size)

    if args.mc:
        print(f"\nRunning backtest for Monte Carlo input...")
        config = BacktestConfig(instrument=args.instrument, timeframe=args.timeframe,
            start_date=start_date, end_date=end_date, initial_balance=args.balance,
            risk_per_trade_pct=0.5, spread_pips=1.2, pip_size=pip_size)
        results = BacktestEngine(config).run(strategy)
        if len(results.trades) < 10:
            print(f"\n✗ Not enough trades ({len(results.trades)} trades, need 10+)\n")
        else:
            print(f"  {len(results.trades)} trades. Running {args.mc_sims:,} simulations...")
            mc = MonteCarlo(results, MonteCarloConfig(n_simulations=args.mc_sims))
            MonteCarlo.print_report(mc.run())

    if args.wf:
        print(f"\nRunning Walk-Forward Validation...")
        validator = WalkForwardValidator(instrument=args.instrument, timeframe=args.timeframe,
            full_start=start_date, full_end=end_date, n_windows=args.wf_windows,
            oos_pct=0.3, initial_balance=args.balance, risk_per_trade_pct=0.5,
            spread_pips=1.2, pip_size=pip_size)
        WalkForwardValidator.print_report(validator.run(strategy))

if __name__ == "__main__":
    main()
