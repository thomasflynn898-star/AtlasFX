"""
monitoring/health_check.py
AtlasFX Self-Healing Diagnostic System

Runs every 2 hours during trading hours (07:00-17:00 UTC).
Detects silence vs errors and sends Telegram alerts.
"""
from __future__ import annotations
import traceback
from datetime import datetime, timezone
from typing import Optional
from logs.logger import get_logger

log = get_logger(__name__)


class HealthCheck:
    """
    Monitors AtlasFX health and distinguishes between:
    - Market silence (no setups) — normal, no alert needed
    - Filter silence (ADX too low, range wrong) — informational
    - Code errors (strategy crashed) — urgent alert
    """

    def __init__(self, broker=None, telegram=None):
        self._broker = broker
        self._telegram = telegram
        self._last_signal_time: Optional[datetime] = None
        self._last_health_report: Optional[datetime] = None
        self._error_count = 0
        self._scan_count = 0
        self._signal_count = 0
        self._strategy_errors: list = []

    def record_scan(self):
        self._scan_count += 1

    def record_signal(self, instrument: str, strategy: str):
        self._last_signal_time = datetime.now(timezone.utc)
        self._signal_count += 1

    def record_error(self, error: str, instrument: str = ""):
        self._error_count += 1
        self._strategy_errors.append({
            "time": datetime.now(timezone.utc).strftime("%H:%M UTC"),
            "instrument": instrument,
            "error": error[:100]
        })
        # Keep last 10 errors only
        self._strategy_errors = self._strategy_errors[-10:]
        log.error("health_check_error", instrument=instrument, error=error[:100])

    def run_diagnostic(self) -> dict:
        """Run full diagnostic and return status report"""
        now = datetime.now(timezone.utc)
        hour = now.hour
        dow = now.weekday()

        result = {
            "timestamp": now.strftime("%H:%M UTC"),
            "status": "OK",
            "alerts": [],
            "info": [],
            "market_status": "",
            "pairs": []
        }

        # Check if we're in trading hours
        if dow in [5, 6]:
            result["market_status"] = "WEEKEND"
            result["info"].append("Weekend — no trading")
            return result

        if dow in [0, 4]:
            result["market_status"] = "NO_TRADE_DAY"
            result["info"].append("Monday/Friday — trading disabled by design")
            return result

        in_london = 7 <= hour < 14
        in_ny = 14 <= hour < 17
        in_ema = 7 <= hour < 16

        if not (in_london or in_ny or in_ema):
            result["market_status"] = "OUTSIDE_HOURS"
            result["info"].append(f"Outside trading hours ({hour:02d}:00 UTC)")
            return result

        # We're in trading hours — run diagnostics
        if in_london:
            result["market_status"] = "LONDON_ORB_ACTIVE"
        elif in_ny:
            result["market_status"] = "NY_ORB_ACTIVE"
        else:
            result["market_status"] = "EMA_ACTIVE"

        # Check for errors
        if self._strategy_errors:
            result["status"] = "ERROR"
            result["alerts"].append(f"🚨 {len(self._strategy_errors)} strategy errors detected")
            for e in self._strategy_errors[-3:]:
                result["alerts"].append(f"  {e['time']} {e['instrument']}: {e['error']}")

        # Check silence duration
        hours_silent = 0
        if self._last_signal_time:
            hours_silent = (now - self._last_signal_time).total_seconds() / 3600
        else:
            # No signal ever fired — check how long agent has been running
            hours_silent = 999

        # Diagnose pairs
        if self._broker:
            try:
                pairs = [
                    ("EUR_USD", 0.0001), ("GBP_USD", 0.0001),
                    ("USD_JPY", 0.01), ("USD_CAD", 0.0001),
                    ("NZD_USD", 0.0001), ("EUR_CAD", 0.0001),
                ]
                inside_range = []
                broken_out = []
                low_adx = []

                import pandas as pd
                import numpy as np

                for inst, pip in pairs:
                    try:
                        candles = self._broker.get_candles(inst, "H1", 50)
                        df = pd.DataFrame(candles)
                        df.index = pd.to_datetime(df["time"])
                        df = df.rename(columns={"open":"Open","high":"High",
                            "low":"Low","close":"Close","volume":"Volume"})
                        df = df[["Open","High","Low","Close","Volume"]].astype(float).sort_index()

                        today = df.index[-1].date()
                        asian = df[(df.index.date == today) & (df.index.hour < 7)]
                        if len(asian) < 2:
                            continue

                        ah = float(asian["High"].max())
                        al = float(asian["Low"].min())
                        ar = ah - al
                        cur = float(df["Close"].iloc[-1])

                        # ADX
                        h = df["High"]; l = df["Low"]; c = df["Close"]
                        tr = pd.concat([h-l, abs(h-c.shift()), abs(l-c.shift())], axis=1).max(axis=1)
                        up = h.diff(); dn = -l.diff()
                        dmp = pd.Series(np.where((up>dn)&(up>0), up, 0), index=h.index)
                        dmm = pd.Series(np.where((dn>up)&(dn>0), dn, 0), index=h.index)
                        atr = tr.ewm(span=14, adjust=False).mean()
                        dip = (dmp.ewm(span=14, adjust=False).mean() / atr.replace(0, 1e-9)) * 100
                        dim = (dmm.ewm(span=14, adjust=False).mean() / atr.replace(0, 1e-9)) * 100
                        dx = (abs(dip-dim) / (dip+dim).replace(0, 1e-9)) * 100
                        adx_val = float(dx.ewm(span=14, adjust=False).mean().iloc[-1])

                        pair_info = {
                            "instrument": inst,
                            "range_pips": round(ar/pip, 1),
                            "adx": round(adx_val, 1),
                            "position": "INSIDE" if al <= cur <= ah else ("ABOVE" if cur > ah else "BELOW"),
                            "pips_from_range": round(abs(cur-ah)/pip if cur > ah else abs(al-cur)/pip, 1)
                        }
                        result["pairs"].append(pair_info)

                        if adx_val < 20:
                            low_adx.append(f"{inst.replace('_','/')} ADX={round(adx_val,1)}")
                        if al <= cur <= ah:
                            inside_range.append(inst.replace("_","/"))
                        else:
                            broken_out.append(inst.replace("_","/"))

                    except Exception as e:
                        result["alerts"].append(f"⚠️ {inst} data error: {str(e)[:50]}")

                # Summarise findings
                if len(inside_range) == len(pairs):
                    result["info"].append(f"All {len(pairs)} pairs inside Asian range — waiting for breakout")
                elif broken_out:
                    result["info"].append(f"Broken out: {', '.join(broken_out)}")
                    result["info"].append(f"Inside range: {', '.join(inside_range)}")

                if low_adx:
                    result["info"].append(f"Low ADX (choppy): {', '.join(low_adx)}")

            except Exception as e:
                result["alerts"].append(f"🚨 Broker diagnostic failed: {str(e)[:80]}")
                result["status"] = "ERROR"

        # Silence alert — only if in trading hours for >3 hours
        if hours_silent > 3 and result["market_status"] not in ["OUTSIDE_HOURS","WEEKEND","NO_TRADE_DAY"]:
            if not result["alerts"]:  # No errors — market silence
                result["info"].append(f"No signals for {hours_silent:.1f}hrs — market conditions not met")
            else:
                result["status"] = "ERROR"

        return result

    def send_health_report(self, force: bool = False):
        """Send health report via Telegram"""
        now = datetime.now(timezone.utc)

        # Only report every 3 hours during trading hours, or if forced
        if not force and self._last_health_report:
            hours_since = (now - self._last_health_report).total_seconds() / 3600
            if hours_since < 3:
                return

        result = self.run_diagnostic()

        # Don't send report outside trading hours unless forced or error
        if result["market_status"] in ["OUTSIDE_HOURS", "WEEKEND"] and not force:
            return

        if not self._telegram:
            return

        self._last_health_report = now

        # Build message
        status_emoji = {
            "OK": "✅",
            "WARNING": "⚠️",
            "ERROR": "🚨"
        }.get(result["status"], "❓")

        lines = [
            f"{status_emoji} AtlasFX Health Check",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"Status: {result['status']}",
            f"Session: {result['market_status'].replace('_',' ')}",
            f"Scans: {self._scan_count} | Signals: {self._signal_count}",
            ""
        ]

        if result["alerts"]:
            lines.append("ALERTS:")
            lines.extend(result["alerts"])
            lines.append("")

        if result["info"]:
            lines.extend(result["info"])
            lines.append("")

        if result["pairs"]:
            lines.append("Pair status:")
            for p in result["pairs"]:
                pos_str = "📍" if p["position"] == "INSIDE" else ("📈" if p["position"] == "ABOVE" else "📉")
                lines.append(f"  {pos_str} {p['instrument'].replace('_','/')} "
                           f"ADX:{p['adx']} Range:{p['range_pips']}p")

        lines.append(f"━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"{result['timestamp']}")

        self._telegram.send("\n".join(lines), parse_mode="")

        # Log
        log.info("health_check_sent", status=result["status"],
                 market=result["market_status"])
