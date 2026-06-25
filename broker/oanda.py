from __future__ import annotations
import time
from datetime import datetime
from typing import Optional
import requests
from broker.base import AccountInfo, BaseBroker, OpenTrade, OrderResult, Price
from logs.logger import get_logger
log = get_logger(__name__)

GRANULARITY_MAP = {"M1":"M1","M5":"M5","M15":"M15","M30":"M30","H1":"H1","H4":"H4","D":"D","W":"W"}

class OANDABroker(BaseBroker):
    def __init__(self, api_key, account_id, environment="practice", request_timeout=10, min_request_interval=0.1):
        if not api_key: raise ValueError("OANDA API key is required")
        if not account_id: raise ValueError("OANDA account ID is required")
        if environment not in ("practice","live"): raise ValueError(f"environment must be practice or live, got {environment}")
        self._api_key = api_key
        self._account_id = account_id
        self._environment = environment
        self._timeout = request_timeout
        self._min_interval = min_request_interval
        self._last_request_time = 0.0
        self._connected = False
        self._base_url = "https://api-fxtrade.oanda.com" if environment=="live" else "https://api-fxpractice.oanda.com"
        self._session = requests.Session()
        self._session.headers.update({"Authorization":f"Bearer {self._api_key}","Content-Type":"application/json","Accept-Datetime-Format":"RFC3339"})
        log.info("oanda_broker_initialised", environment=environment, account_id=account_id)

    def _request(self, method, endpoint, params=None, json=None):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval: time.sleep(self._min_interval - elapsed)
        url = f"{self._base_url}{endpoint}"
        try:
            r = self._session.request(method=method, url=url, params=params, json=json, timeout=self._timeout)
            self._last_request_time = time.time()
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            log.error("oanda_http_error", status=e.response.status_code, endpoint=endpoint, body=e.response.text[:200])
            raise
        except requests.ConnectionError as e:
            log.error("oanda_connection_error", endpoint=endpoint, error=str(e))
            raise

    def test_connection(self):
        try:
            self.get_account()
            self._connected = True
            log.info("oanda_connection_verified")
            return True
        except Exception as e:
            self._connected = False
            log.error("oanda_connection_failed", error=str(e))
            return False

    @property
    def is_connected(self): return self._connected
    @property
    def name(self): return f"OANDA ({self._environment})"

    def get_account(self):
        data = self._request("GET", f"/v3/accounts/{self._account_id}/summary")
        a = data["account"]
        self._connected = True
        return AccountInfo(account_id=a["id"], balance=float(a["balance"]), nav=float(a["NAV"]),
            unrealised_pnl=float(a["unrealizedPL"]), margin_used=float(a["marginUsed"]),
            margin_available=float(a["marginAvailable"]), currency=a["currency"],
            open_trade_count=int(a["openTradeCount"]))

    def get_price(self, instrument):
        data = self._request("GET", f"/v3/accounts/{self._account_id}/pricing", params={"instruments":instrument})
        p = data["prices"][0]
        return Price(instrument=instrument, bid=float(p["bids"][0]["price"]), ask=float(p["asks"][0]["price"]),
            timestamp=datetime.fromisoformat(p["time"].replace("Z","+00:00")))

    def get_open_trades(self):
        data = self._request("GET", f"/v3/accounts/{self._account_id}/openTrades")
        trades = []
        for t in data.get("trades",[]):
            units = float(t["currentUnits"])
            sl = float(t["stopLossOrder"]["price"]) if "stopLossOrder" in t else None
            tp = float(t["takeProfitOrder"]["price"]) if "takeProfitOrder" in t else None
            trades.append(OpenTrade(trade_id=t["id"], instrument=t["instrument"],
                direction="BUY" if units>0 else "SELL", units=abs(units),
                entry_price=float(t["price"]), current_price=float(t["price"]),
                stop_loss=sl, take_profit=tp, unrealised_pnl=float(t["unrealizedPL"]),
                open_time=datetime.fromisoformat(t["openTime"].replace("Z","+00:00"))))
        return trades

    def submit_market_order(self, instrument, direction, units, stop_loss, take_profit):
        if direction not in ("BUY","SELL"):
            return OrderResult(success=False,order_id=None,trade_id=None,instrument=instrument,
                direction=direction,units=units,entry_price=0,stop_loss=stop_loss,take_profit=take_profit,
                error_message=f"Invalid direction: {direction}")
        signed_units = units if direction=="BUY" else -units
        prec = 3 if "JPY" in instrument else 2 if "XAU" in instrument else 5
        body = {"order":{"type":"MARKET","instrument":instrument,"units":str(int(signed_units)),
            "timeInForce":"FOK","positionFill":"DEFAULT",
            "stopLossOnFill":{"price":str(round(stop_loss,prec)),"timeInForce":"GTC"},
            "takeProfitOnFill":{"price":str(round(take_profit,prec)),"timeInForce":"GTC"}}}
        log.info("oanda_order_submitting",instrument=instrument,direction=direction,units=int(signed_units))
        try:
            data = self._request("POST", f"/v3/accounts/{self._account_id}/orders", json=body)
            fill = data.get("orderFillTransaction",{})
            if fill:
                trade_id = fill.get("tradeOpened",{}).get("tradeID")
                entry_price = float(fill.get("price",0))
                log.info("oanda_order_filled",instrument=instrument,trade_id=trade_id,entry_price=entry_price)
                return OrderResult(success=True,order_id=fill.get("orderID"),trade_id=trade_id,
                    instrument=instrument,direction=direction,units=units,entry_price=entry_price,
                    stop_loss=stop_loss,take_profit=take_profit)
            cancel = data.get("orderCancelTransaction",{})
            reason = cancel.get("reason","Unknown rejection")
            log.warning("oanda_order_rejected",reason=reason)
            return OrderResult(success=False,order_id=None,trade_id=None,instrument=instrument,
                direction=direction,units=units,entry_price=0,stop_loss=stop_loss,take_profit=take_profit,
                error_message=reason)
        except Exception as e:
            log.error("oanda_order_failed",error=str(e))
            return OrderResult(success=False,order_id=None,trade_id=None,instrument=instrument,
                direction=direction,units=units,entry_price=0,stop_loss=stop_loss,take_profit=take_profit,
                error_message=str(e))

    def close_trade(self, trade_id):
        try:
            self._request("PUT", f"/v3/accounts/{self._account_id}/trades/{trade_id}/close")
            log.info("oanda_trade_closed",trade_id=trade_id)
            return True
        except Exception as e:
            log.error("oanda_close_failed",trade_id=trade_id,error=str(e))
            return False

    def modify_trade(self, trade_id, stop_loss=None, take_profit=None):
        orders = {}
        if stop_loss: orders["stopLoss"] = {"price":str(round(stop_loss,5)),"timeInForce":"GTC"}
        if take_profit: orders["takeProfit"] = {"price":str(round(take_profit,5)),"timeInForce":"GTC"}
        if not orders: return True
        try:
            self._request("PUT", f"/v3/accounts/{self._account_id}/trades/{trade_id}/orders", json=orders)
            return True
        except Exception as e:
            log.error("oanda_modify_failed",trade_id=trade_id,error=str(e))
            return False

    def get_candles(self, instrument, granularity, count=500):
        g = GRANULARITY_MAP.get(granularity, granularity)
        data = self._request("GET", f"/v3/instruments/{instrument}/candles",
            params={"granularity":g,"count":min(count,5000),"price":"M"})
        candles = []
        for c in data.get("candles",[]):
            if not c.get("complete",True): continue
            m = c["mid"]
            candles.append({"time":c["time"],"open":float(m["o"]),"high":float(m["h"]),
                "low":float(m["l"]),"close":float(m["c"]),"volume":int(c.get("volume",0))})
        return candles

    def get_candles_as_dataframe(self, instrument, granularity, count=500):
        import pandas as pd
        candles = self.get_candles(instrument, granularity, count)
        if not candles: return pd.DataFrame()
        df = pd.DataFrame(candles)
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)
        df = df.set_index("time")
        df.columns = [c.capitalize() for c in df.columns]
        return df
