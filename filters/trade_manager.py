from __future__ import annotations
import math
from logs.logger import get_logger
log = get_logger(__name__)

def _safe(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

class TradeManager:
    """
    Trade manager — trailing stop and H4 invalidation disabled.
    Both features were never part of the validated ORB/EMA backtest.
    Trades now run to their original SL/TP only.
    """
    def __init__(self, broker):
        self._broker = broker

    def evaluate(self, trade_id, position):
        """Hold all trades to original SL/TP — no early exits."""
        return {close: False, close_reason: None,
                modify_sl: False, new_sl: None, action: hold}
