from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from backtesting.engine import BacktestResults
from logs.logger import get_logger
log = get_logger(__name__)

@dataclass
class MonteCarloConfig:
    n_simulations: int = 10_000
    ruin_threshold_pct: float = 20.0
    confidence_levels: list = field(default_factory=lambda: [0.05,0.25,0.50,0.75,0.95])
    random_seed: Optional[int] = 42

@dataclass
class MonteCarloReport:
    strategy_id: str
    instrument: str
    n_trades: int
    n_simulations: int
    initial_balance: float
    probability_of_ruin_pct: float
    probability_of_profit_pct: float
    median_return_pct: float
    mean_return_pct: float
    median_max_drawdown_pct: float
    worst_case_drawdown_pct: float
    expected_max_drawdown_pct: float
    return_percentiles: dict
    median_max_consecutive_losses: float
    worst_case_consecutive_losses: int
    original_return_pct: float
    original_win_rate_pct: float
    original_profit_factor: float
    verdict: str
    verdict_reasons: list
    all_final_returns: list = field(default_factory=list)
    all_max_drawdowns: list = field(default_factory=list)
    sample_equity_curves: list = field(default_factory=list)

class MonteCarlo:
    def __init__(self, results: BacktestResults, config: Optional[MonteCarloConfig] = None):
        self.results = results
        self.config = config or MonteCarloConfig()
        if len(results.trades) < 10:
            raise ValueError(f"Monte Carlo requires at least 10 trades. Got {len(results.trades)}.")
        self.r_multiples = np.array([t.r_multiple for t in results.trades])
        self.initial_balance = results.config.initial_balance
        self.risk_pct = results.config.risk_per_trade_pct / 100

    def _simulate_single_path(self, rng, r_multiples):
        n_trades = len(r_multiples)
        sampled_rs = rng.choice(r_multiples, size=n_trades, replace=True)
        equity = self.initial_balance
        peak = equity
        max_dd = 0.0
        equity_curve = [equity]
        max_consec_losses = 0
        current_consec = 0
        for r in sampled_rs:
            if r > 0:
                equity *= (1 + self.risk_pct * r)
                current_consec = 0
            else:
                equity *= (1 + self.risk_pct * r)
                current_consec += 1
                max_consec_losses = max(max_consec_losses, current_consec)
            equity = max(equity, 0.01)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
            equity_curve.append(equity)
        return equity_curve, max_dd, max_consec_losses

    def run(self) -> MonteCarloReport:
        rng = np.random.default_rng(self.config.random_seed)
        final_returns, max_drawdowns, consecutive_losses, sample_curves = [], [], [], []
        ruin_count = 0
        ruin_threshold = self.initial_balance * (1 - self.config.ruin_threshold_pct / 100)
        for i in range(self.config.n_simulations):
            curve, max_dd, max_consec = self._simulate_single_path(rng, self.r_multiples)
            final_equity = curve[-1]
            final_return_pct = (final_equity / self.initial_balance - 1) * 100
            final_returns.append(final_return_pct)
            max_drawdowns.append(max_dd)
            consecutive_losses.append(max_consec)
            if final_equity <= ruin_threshold or max_dd >= self.config.ruin_threshold_pct:
                ruin_count += 1
            if i < 50:
                sample_curves.append(curve)
        returns_arr = np.array(final_returns)
        dd_arr = np.array(max_drawdowns)
        consec_arr = np.array(consecutive_losses)
        pv = np.percentile(returns_arr, [5,25,50,75,95])
        return_percentiles = {"p5":round(float(pv[0]),2),"p25":round(float(pv[1]),2),"p50":round(float(pv[2]),2),"p75":round(float(pv[3]),2),"p95":round(float(pv[4]),2)}
        probability_of_ruin = ruin_count / self.config.n_simulations * 100
        probability_of_profit = float(np.sum(returns_arr > 0)) / self.config.n_simulations * 100
        orig = self.results.summary()
        verdict, reasons = self._generate_verdict(probability_of_ruin, probability_of_profit, float(np.median(returns_arr)), float(np.percentile(dd_arr,95)), orig.get("win_rate_pct",0), orig.get("profit_factor",0), len(self.results.trades))
        return MonteCarloReport(
            strategy_id=self.results.strategy_id, instrument=self.results.config.instrument,
            n_trades=len(self.results.trades), n_simulations=self.config.n_simulations,
            initial_balance=self.initial_balance,
            probability_of_ruin_pct=round(probability_of_ruin,2),
            probability_of_profit_pct=round(probability_of_profit,2),
            median_return_pct=round(float(np.median(returns_arr)),2),
            mean_return_pct=round(float(np.mean(returns_arr)),2),
            median_max_drawdown_pct=round(float(np.median(dd_arr)),2),
            worst_case_drawdown_pct=round(float(np.percentile(dd_arr,95)),2),
            expected_max_drawdown_pct=round(float(np.mean(dd_arr)),2),
            return_percentiles=return_percentiles,
            median_max_consecutive_losses=round(float(np.median(consec_arr)),1),
            worst_case_consecutive_losses=int(np.percentile(consec_arr,95)),
            original_return_pct=round(orig.get("total_return_pct",0),2),
            original_win_rate_pct=round(orig.get("win_rate_pct",0),2),
            original_profit_factor=round(orig.get("profit_factor",0),3),
            verdict=verdict, verdict_reasons=reasons,
            all_final_returns=final_returns, all_max_drawdowns=list(max_drawdowns),
            sample_equity_curves=sample_curves)

    def _generate_verdict(self, probability_of_ruin, probability_of_profit, median_return, worst_dd, orig_win_rate, orig_profit_factor, n_trades):
        reasons = []
        fail_count = 0
        warn_count = 0
        if n_trades < 30:
            reasons.append(f"INSUFFICIENT SAMPLE: {n_trades} trades (minimum 30)")
            fail_count += 1
        elif n_trades < 100:
            reasons.append(f"SMALL SAMPLE: {n_trades} trades — wide confidence intervals")
            warn_count += 1
        else:
            reasons.append(f"Sample size: {n_trades} trades")
        if probability_of_ruin >= 15:
            reasons.append(f"FAIL: Ruin probability {probability_of_ruin:.1f}% too high")
            fail_count += 1
        elif probability_of_ruin >= 5:
            reasons.append(f"WARNING: Ruin probability {probability_of_ruin:.1f}% elevated")
            warn_count += 1
        else:
            reasons.append(f"PASS: Ruin probability {probability_of_ruin:.1f}%")
        if probability_of_profit <= 45:
            reasons.append(f"FAIL: Only {probability_of_profit:.1f}% of paths profitable")
            fail_count += 1
        elif probability_of_profit <= 60:
            reasons.append(f"WARNING: {probability_of_profit:.1f}% of paths profitable")
            warn_count += 1
        else:
            reasons.append(f"PASS: {probability_of_profit:.1f}% of paths profitable")
        if median_return < 0:
            reasons.append(f"FAIL: Median return {median_return:.2f}% negative")
            fail_count += 1
        elif median_return < 1:
            reasons.append(f"WARNING: Median return {median_return:.2f}% marginal")
            warn_count += 1
        else:
            reasons.append(f"PASS: Median return {median_return:.2f}%")
        if worst_dd >= 30:
            reasons.append(f"FAIL: 95th pct drawdown {worst_dd:.1f}% too severe")
            fail_count += 1
        elif worst_dd >= 20:
            reasons.append(f"WARNING: 95th pct drawdown {worst_dd:.1f}% significant")
            warn_count += 1
        else:
            reasons.append(f"PASS: 95th pct drawdown {worst_dd:.1f}%")
        if orig_profit_factor < 1.0:
            reasons.append(f"FAIL: Profit factor {orig_profit_factor:.3f} < 1.0")
            fail_count += 1
        elif orig_profit_factor < 1.3:
            reasons.append(f"WARNING: Profit factor {orig_profit_factor:.3f} marginal")
            warn_count += 1
        else:
            reasons.append(f"PASS: Profit factor {orig_profit_factor:.3f}")
        verdict = "FAIL" if fail_count > 0 else "MARGINAL" if warn_count >= 1 else "PASS"
        return verdict, reasons

    @staticmethod
    def print_report(report: MonteCarloReport):
        w = 62
        symbols = {"PASS":"✓","MARGINAL":"~","FAIL":"✗"}
        sym = symbols.get(report.verdict,"?")
        print("\n" + "="*w)
        print(f"  MONTE CARLO ANALYSIS — {report.strategy_id}")
        print(f"  {report.instrument}  |  {report.n_simulations:,} simulations  |  {report.n_trades} trades")
        print("="*w)
        print(f"\n  ORIGINAL BACKTEST")
        print(f"  Return          : {report.original_return_pct:+.2f}%")
        print(f"  Win rate        : {report.original_win_rate_pct:.1f}%")
        print(f"  Profit factor   : {report.original_profit_factor:.3f}")
        print(f"\n  MONTE CARLO RESULTS")
        print(f"  Probability of ruin   : {report.probability_of_ruin_pct:.2f}%")
        print(f"  Probability of profit : {report.probability_of_profit_pct:.1f}%")
        print(f"  Median return         : {report.median_return_pct:+.2f}%")
        print(f"  Mean return           : {report.mean_return_pct:+.2f}%")
        print(f"\n  RETURN DISTRIBUTION")
        p = report.return_percentiles
        print(f"  Worst 5%   (p5)  : {p['p5']:+.2f}%")
        print(f"  Lower 25%  (p25) : {p['p25']:+.2f}%")
        print(f"  Median     (p50) : {p['p50']:+.2f}%")
        print(f"  Upper 75%  (p75) : {p['p75']:+.2f}%")
        print(f"  Best 5%    (p95) : {p['p95']:+.2f}%")
        print(f"\n  DRAWDOWN ANALYSIS")
        print(f"  Median max DD         : {report.median_max_drawdown_pct:.2f}%")
        print(f"  Worst case (95th pct) : {report.worst_case_drawdown_pct:.2f}%")
        print(f"\n  VERDICT: {sym} {report.verdict}")
        for r in report.verdict_reasons:
            pre = "  ✗ " if r.startswith("FAIL") else "  ~ " if r.startswith("WARNING") else "  ✓ " if r.startswith("PASS") else "  ! "
            print(f"{pre}{r}")
        print(f"\n  NOTE: Simulated estimates only.")
        print("="*w + "\n")
