from __future__ import annotations
from datetime import datetime
from typing import Optional
import requests
from logs.logger import get_logger
log = get_logger(__name__)

class NotificationEngine:
    def __init__(self, pushover_token=None, pushover_user=None,
                 telegram_token=None, telegram_chat_id=None):
        self._pushover_token = pushover_token
        self._pushover_user = pushover_user
        self._telegram_token = telegram_token
        self._telegram_chat_id = telegram_chat_id

    @classmethod
    def from_settings(cls):
        from config.settings import settings
        return cls(pushover_token=settings.pushover_api_token,
            pushover_user=settings.pushover_user_key,
            telegram_token=settings.telegram_bot_token,
            telegram_chat_id=settings.telegram_chat_id)

    def send(self, title, message, notification_type="info", priority=0):
        log.info("notification", type=notification_type, title=title)
        success = False
        if self._pushover_token and self._pushover_user:
            success = self._send_pushover(title, message, priority) or success
        if self._telegram_token and self._telegram_chat_id:
            success = self._send_telegram(title, message) or success
        if not success:
            log.info("notification_log_only", title=title, message=message)
        return True

    def _send_pushover(self, title, message, priority=0):
        try:
            r = requests.post("https://api.pushover.net/1/messages.json",
                data={"token":self._pushover_token,"user":self._pushover_user,
                      "title":title,"message":message,"priority":priority}, timeout=5)
            return r.status_code == 200
        except Exception as e:
            log.error("pushover_error", error=str(e)); return False

    def _send_telegram(self, title, message):
        try:
            text = "*" + title + "*" + chr(10) + message
            r = requests.post(
                "https://api.telegram.org/bot" + self._telegram_token + "/sendMessage",
                json={"chat_id":self._telegram_chat_id,"text":text,"parse_mode":"Markdown"},
                timeout=5)
            return r.status_code == 200
        except Exception as e:
            log.error("telegram_error", error=str(e)); return False

    def trade_opened(self, instrument, direction, entry, sl, tp, units, strategy, is_paper=True):
        mode = "DEMO" if is_paper else "LIVE"
        rr = round(abs(tp-entry)/abs(sl-entry),1) if sl!=entry else 0
        msg = instrument + " " + direction + chr(10)
        msg += "Entry:" + str(round(entry,5)) + " SL:" + str(round(sl,5)) + " TP:" + str(round(tp,5)) + chr(10)
        msg += "RR 1:" + str(rr) + "  Units:" + str(int(units)) + chr(10) + strategy
        self.send(mode + " Trade Opened", msg, "trade_opened")

    def trade_closed(self, instrument, direction, pnl, r_multiple, close_reason, is_paper=True):
        mode = "DEMO" if is_paper else "LIVE"
        emoji = "OK" if pnl >= 0 else "XX"
        msg = instrument + " " + direction + chr(10)
        msg += "PnL:" + str(round(pnl,2)) + "  R:" + str(round(r_multiple,2)) + chr(10) + close_reason
        self.send(mode + " Trade Closed " + emoji, msg, "trade_closed")

    def daily_report(self, date, trades, pnl, win_rate, balance):
        msg = "Date:" + date + chr(10)
        msg += "Trades:" + str(trades) + "  WR:" + str(round(win_rate,1)) + "%" + chr(10)
        msg += "PnL:" + str(round(pnl,2)) + chr(10) + "Balance:" + str(round(balance,2))
        self.send("Daily Report", msg, "daily_report")

    def risk_alert(self, message):
        self.send("Risk Alert", message, "risk_alert", priority=1)

    def agent_started(self):
        self.send("Agent Started", "Paper trading running " + datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

    def agent_stopped(self, reason="Manual stop"):
        self.send("Agent Stopped", "Reason: " + reason)

    def error(self, msg):
        self.send("Error", msg, "error", priority=1)
