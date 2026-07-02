"""
telegram/bot.py — AtlasFX Intelligent Trading Bot
- Commands: /status /close /trades /pause /resume /pairs /daily /help
- Natural language: Claude AI responds with full AtlasFX context
- Auto-close: closes positions on request
- Proactive: trade events only
"""
from __future__ import annotations
import threading
import time
import requests
from datetime import datetime, timezone
from typing import Optional, Callable
from logs.logger import get_logger

log = get_logger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are the AtlasFX trading bot assistant. You have full knowledge of the AtlasFX autonomous FX trading platform.

SYSTEM OVERVIEW:
- AtlasFX runs 3 validated strategies on a VPS (158.220.93.163)
- London ORB: 07:00-14:00 UTC | Asian range breakout | ADX>25 | 1.5R
- NY ORB: 14:00-17:00 UTC | NY range breakout | ADX>25 | 1.5R  
- EMA Pullback: 07:00-16:00 UTC | 21 EMA bounce | ADX>35 | 2.5R
- Risk: 1% per trade | No Mon/Fri trading

VALIDATED PAIRS:
- London ORB: EUR/USD, GBP/USD, USD/JPY, USD/CAD, NZD/USD, EUR/CAD, EUR/JPY (probationary)
- NY ORB: EUR/USD, GBP/USD, USD/JPY, USD/CAD, NZD/USD, EUR/CAD, GBP/AUD, EUR/NZD, GBP/NZD, NZD/JPY
- EMA Pullback: GBP/USD, USD/JPY, AUD/CHF, GBP/NZD

PERFORMANCE:
- Backtested WR: 57.5-60% blended | PF: 2.0+
- Live record since reboot: ~87% WR (small sample)
- Best day: +£2,933 | Account started £100,000

CONFIDENCE SCORING (1-10):
- 9-10: Near TP, strong trend
- 7-8: Good progress, on track
- 6-7: At entry/retest level — NORMAL for ORB, do not panic
- 4-5: Slight pullback, watching
- 2-3: Threatening SL, consider action
- <4: LOW CONFIDENCE WARNING issued

RULES:
- ORB pullbacks to entry level are NORMAL — price retesting the breakout is healthy
- Only panic when price threatens the SL (within 15% of SL distance)
- No trades Monday or Friday
- London session (07:00-14:00 UTC) and NY session (14:00-17:00 UTC) are the only trading windows

You have access to live account data provided in each message. Be direct, confident and knowledgeable. 
Keep responses concise for Telegram. Use plain text — no markdown headers, minimal formatting.
When asked about trades, give a clear recommendation. Don't be wishy-washy."""


def confidence_score(direction, entry, current, sl, tp, adx=0):
    if sl == entry or tp == entry: return 5
    total = abs(tp - entry)
    dist_sl = abs(current - sl)
    dist_tp = abs(tp - current)
    progress = (current - entry) if direction == "BUY" else (entry - current)
    pct = progress / total if total > 0 else 0
    sl_threat = dist_sl / abs(tp - entry) if abs(tp - entry) > 0 else 1

    if sl_threat < 0.15: base = 2
    elif sl_threat < 0.25: base = 3
    elif pct >= 0.75: base = 9
    elif pct >= 0.5: base = 8
    elif pct >= 0.25: base = 7
    elif pct >= 0: base = 7
    elif pct >= -0.2: base = 6
    elif pct >= -0.4: base = 5
    else: base = 3

    adx_bonus = 1 if adx >= 35 else (0 if adx >= 25 else -1)
    return max(1, min(10, base + adx_bonus))


def conf_bar(s): return chr(9608) * s + chr(9617) * (10 - s)


def conf_label(s):
    if s >= 8: return "STRONG ✅"
    if s >= 6: return "GOOD 🟢"
    if s >= 5: return "NEUTRAL 🟡"
    if s >= 4: return "WEAK 🟠"
    return "DANGER ⛔"


class TelegramBot:
    POLL_INTERVAL = 10

    def __init__(self, token: str, chat_id: str):
        self._token = token
        self._chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{token}"
        self._last_update_id = 0
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._handlers: dict = {}
        self._start_time = time.time()
        self._paused = False
        self._broker = None
        self._db = None
        self._conversation_history = []

        # Fast-forward update queue — consume ALL pending messages on startup
        try:
            r = requests.get(f"{self._base}/getUpdates",
                params={"offset": -1, "limit": 100}, timeout=5)
            results = r.json().get("result", [])
            if results:
                self._last_update_id = results[-1]["update_id"]
                # Confirm consumption
                requests.get(f"{self._base}/getUpdates",
                    params={"offset": self._last_update_id + 1, "limit": 1}, timeout=5)
                log.info("telegram_queue_cleared", consumed=len(results),
                         last_id=self._last_update_id)
        except Exception as e:
            log.debug("telegram_queue_clear_failed", error=str(e))

        log.info("telegram_bot_initialised", chat_id=chat_id, last_update=self._last_update_id)

    def set_broker(self, broker):
        """Inject broker for live data access"""
        self._broker = broker

    def set_db(self, db):
        """Inject database for trade history"""
        self._db = db

    def register_handler(self, command: str, handler: Callable):
        self._handlers[command] = handler

    def is_paused(self) -> bool:
        return self._paused

    def start_polling(self):
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="telegram-poll")
        self._poll_thread.start()

    def stop_polling(self):
        self._running = False

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        try:
            r = requests.post(f"{self._base}/sendMessage",
                json={"chat_id": self._chat_id, "text": message,
                      "parse_mode": parse_mode}, timeout=10)
            return r.status_code == 200
        except Exception as e:
            log.error("telegram_send_failed", error=str(e))
            return False

    def _poll_loop(self):
        while self._running:
            try:
                self._check_updates()
            except Exception as e:
                log.error("telegram_poll_error", error=str(e))
            time.sleep(self.POLL_INTERVAL)

    def _check_updates(self):
        try:
            r = requests.get(f"{self._base}/getUpdates",
                params={"offset": self._last_update_id + 1,
                        "timeout": 5, "allowed_updates": ["message"], "limit": 10},
                timeout=15)
            if r.status_code != 200:
                return
            for update in r.json().get("result", []):
                uid = update["update_id"]
                if uid <= self._last_update_id:
                    continue
                self._last_update_id = uid
                msg = update.get("message", {})
                if msg.get("date", 0) < self._start_time - 5:
                    continue
                text = msg.get("text", "").strip()
                if not text:
                    continue
                if text.startswith("/"):
                    self._handle_command(text)
                else:
                    self._handle_natural_language(text)
        except Exception as e:
            log.debug("telegram_poll_exception", error=str(e))

    def _get_live_context(self) -> str:
        """Build live context string for AI"""
        ctx = []
        now = datetime.now(timezone.utc)
        ctx.append(f"Current UTC time: {now.strftime('%H:%M %Z, %A %d %b %Y')}")

        # Session info
        hour = now.hour
        if 7 <= hour < 14:
            ctx.append("Active session: LONDON ORB (07:00-14:00 UTC)")
        elif 14 <= hour < 17:
            ctx.append("Active session: NY ORB (14:00-17:00 UTC)")
        elif 7 <= hour < 16:
            ctx.append("Active session: EMA Pullback window active")
        else:
            ctx.append("No active trading session (markets quiet)")

        # Account data
        if self._broker:
            try:
                account = self._broker.get_account()
                ctx.append(f"Account balance: £{account.balance:,.2f}")
                ctx.append(f"NAV: £{account.nav:,.2f}")
                ctx.append(f"Unrealised P&L: £{account.unrealised_pnl:,.2f}")
                ctx.append(f"Open positions: {account.open_trade_count}")
            except Exception:
                ctx.append("Account data: unavailable")

        # Open positions
        if self._broker:
            try:
                positions = self._broker.get_open_trades()
                if positions:
                    ctx.append("\nOPEN POSITIONS:")
                    for p in positions:
                        inst = p.instrument.replace('_', '/')
                        pip = 0.01 if 'JPY' in p.instrument or 'XAU' in p.instrument else 0.0001
                        ctx.append(f"  {inst} {p.direction} | Entry: {p.entry_price} | SL: {p.stop_loss} | TP: {p.take_profit} | P&L: £{p.unrealised_pnl:,.2f}")
            except Exception:
                pass

        # Recent closed trades
        if self._db:
            try:
                from data.database import get_session, Trade
                with get_session() as s:
                    recent = s.query(Trade).filter_by(status="CLOSED").order_by(
                        Trade.close_time.desc()).limit(5).all()
                    if recent:
                        ctx.append("\nRECENT CLOSED TRADES:")
                        for t in recent:
                            sign = "+" if t.pnl >= 0 else ""
                            ctx.append(f"  {t.instrument} {t.direction} | {sign}£{t.pnl:.2f} | {t.close_reason}")
            except Exception:
                pass

        ctx.append(f"\nSystem status: {'PAUSED' if self._paused else 'ACTIVE'}")
        return "\n".join(ctx)

    def _ask_claude(self, user_message: str) -> str:
        """Send message to Claude API with full AtlasFX context"""
        try:
            live_ctx = self._get_live_context()
            system = SYSTEM_PROMPT + f"\n\nLIVE DATA:\n{live_ctx}"

            # Keep conversation history (last 6 messages)
            self._conversation_history.append({
                "role": "user", "content": user_message})
            if len(self._conversation_history) > 6:
                self._conversation_history = self._conversation_history[-6:]

            from config.settings import settings as _settings
            api_key = getattr(_settings, 'anthropic_api_key', None)
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01"
            }
            r = requests.post(ANTHROPIC_API_URL,
                headers=headers,
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 500,
                    "system": system,
                    "messages": self._conversation_history
                }, timeout=30)

            if r.status_code == 200:
                response = r.json()["content"][0]["text"]
                self._conversation_history.append({
                    "role": "assistant", "content": response})
                return response
            else:
                return f"AI unavailable ({r.status_code}). Use /status for live data."
        except Exception as e:
            log.error("claude_api_error", error=str(e))
            return "AI temporarily unavailable. Use /status for live data."

    def _handle_natural_language(self, text: str):
        """Handle free-form messages with Claude AI"""
        log.info("telegram_natural_language", message=text[:50])

        # Check for close intent in natural language
        text_lower = text.lower()
        if any(word in text_lower for word in ["close", "exit", "get out", "shut"]):
            # Extract pair if mentioned
            for pair in ["eurusd", "gbpusd", "usdjpy", "usdcad", "nzdusd",
                        "eurcad", "eurjpy", "gbpaud", "eurnzd", "gbpnzd", "nzdjpy",
                        "gbpusd", "usdjpy", "audchf", "gbpnzd"]:
                if pair in text_lower:
                    inst = pair[:3].upper() + "_" + pair[3:].upper()
                    self._execute_close(inst)
                    return

        # Send to Claude
        response = self._ask_claude(text)
        self.send(response, parse_mode="")

    def _handle_command(self, text: str):
        parts = text.split()
        command = parts[0].lower().lstrip("/")
        args = parts[1:]
        log.info("telegram_command", command=command)

        # Built-in commands
        if command == "status":
            self.send(self._cmd_status())
        elif command == "trades":
            self.send(self._cmd_trades())
        elif command == "pairs":
            self.send(self._cmd_pairs())
        elif command == "daily":
            self.send(self._cmd_daily())
        elif command == "pause":
            self._paused = True
            self.send("⏸ AtlasFX PAUSED\nNo new signals will be executed.\nSend /resume to restart.")
        elif command == "resume":
            self._paused = False
            self.send("▶️ AtlasFX RESUMED\nScanning for signals.")
        elif command == "close":
            if args:
                inst = args[0].upper()
                if "_" not in inst and len(inst) == 6:
                    inst = inst[:3] + "_" + inst[3:]
                self._execute_close(inst)
            else:
                self.send("Usage: /close GBPUSD or /close GBP_USD")
        elif command == "help":
            self.send(self._cmd_help())
        elif command in self._handlers:
            try:
                response = self._handlers[command](args)
                if response:
                    self.send(response)
            except Exception as e:
                self.send(f"Error: {e}")
        else:
            # Unknown command — ask Claude
            response = self._ask_claude(text)
            self.send(response, parse_mode="")

    def _execute_close(self, instrument: str):
        """Close a position via broker"""
        if not self._broker:
            self.send(f"Cannot close {instrument} — broker not connected.")
            return
        try:
            result = self._broker.close_position(instrument)
            if result and result.get('success'):
                pnl = result.get('pnl', 0)
                sign = "+" if pnl >= 0 else ""
                self.send(f"✅ CLOSED {instrument.replace('_','/')}\nP&L: {sign}£{pnl:.2f}")
            else:
                self.send(f"❌ Could not close {instrument} — check OANDA manually.")
        except Exception as e:
            self.send(f"❌ Error closing {instrument}: {str(e)}")

    def _cmd_status(self) -> str:
        lines = ["📊 AtlasFX STATUS"]
        lines.append("─────────────────")
        now = datetime.now(timezone.utc)
        hour = now.hour
        dow = now.weekday()

        if dow in [0, 4]:
            lines.append("📅 No trading today (Mon/Fri)")
        elif 7 <= hour < 14:
            lines.append("🟢 London ORB active")
        elif 14 <= hour < 17:
            lines.append("🟢 NY ORB active")
        elif 7 <= hour < 16:
            lines.append("🟡 EMA Pullback window")
        else:
            lines.append("⚫ Outside trading hours")

        if self._paused:
            lines.append("⏸ System: PAUSED")
        else:
            lines.append("✅ System: ACTIVE")

        if self._broker:
            try:
                account = self._broker.get_account()
                lines.append(f"\n💰 Balance: £{account.balance:,.2f}")
                lines.append(f"📈 NAV: £{account.nav:,.2f}")
                pnl = account.unrealised_pnl
                sign = "+" if pnl >= 0 else ""
                lines.append(f"⚡ Unrealised: {sign}£{pnl:,.2f}")
                lines.append(f"📋 Open trades: {account.open_trade_count}")
            except Exception as e:
                lines.append(f"\nAccount error: {str(e)[:100]}")

        if self._broker:
            try:
                positions = self._broker.get_open_trades()
                if positions:
                    lines.append("\n📌 OPEN POSITIONS:")
                    for p in positions:
                        inst = p.instrument.replace('_', '/')
                        sign = "+" if p.unrealised_pnl >= 0 else ""
                        lines.append(f"  {inst} {p.direction} {sign}£{p.unrealised_pnl:.2f}")
            except Exception:
                pass

        lines.append(f"\n🕐 {now.strftime('%H:%M UTC')}")
        return "\n".join(lines)

    def _cmd_trades(self) -> str:
        lines = ["📋 RECENT TRADES"]
        lines.append("─────────────────")
        if self._db:
            try:
                from data.database import get_session, Trade
                with get_session() as s:
                    recent = s.query(Trade).filter_by(status="CLOSED").order_by(
                        Trade.close_time.desc()).limit(8).all()
                    if not recent:
                        lines.append("No closed trades yet")
                    else:
                        wins = 0
                        for t in recent:
                            if t.instrument in ["ADJUSTMENT","RECONCILIATION"]:
                                continue
                            sign = "+" if t.pnl >= 0 else ""
                            emoji = "✅" if t.pnl >= 0 else "❌"
                            lines.append(f"{emoji} {t.instrument.replace('_','/')} {t.direction} {sign}£{t.pnl:.2f}")
                            if t.pnl >= 0:
                                wins += 1
            except Exception as e:
                lines.append(f"Error: {e}")
        else:
            lines.append("Database not connected")
        return "\n".join(lines)

    def _cmd_pairs(self) -> str:
        lines = ["📊 ACTIVE PAIRS"]
        lines.append("─────────────────")
        lines.append("London ORB (07-14 UTC):")
        lines.append("  EUR/USD GBP/USD USD/JPY")
        lines.append("  USD/CAD NZD/USD EUR/CAD EUR/JPY*")
        lines.append("")
        lines.append("NY ORB (14-17 UTC):")
        lines.append("  EUR/USD GBP/USD USD/JPY USD/CAD")
        lines.append("  NZD/USD EUR/CAD GBP/AUD")
        lines.append("  EUR/NZD GBP/NZD NZD/JPY")
        lines.append("")
        lines.append("EMA Pullback (07-16 UTC):")
        lines.append("  GBP/USD USD/JPY AUD/CHF GBP/NZD")
        lines.append("")
        lines.append("*probationary | ⚠️ = WATCH")
        return "\n".join(lines)

    def _cmd_daily(self) -> str:
        lines = ["📅 TODAY'S REPORT"]
        lines.append("─────────────────")
        today = datetime.now(timezone.utc).date()
        if self._db:
            try:
                from data.database import get_session, Trade
                with get_session() as s:
                    trades = s.query(Trade).filter(
                        Trade.status == "CLOSED",
                        Trade.close_time >= datetime.combine(today, datetime.min.time())
                    ).all()
                    trades = [t for t in trades if t.instrument not in ["ADJUSTMENT","RECONCILIATION"]]
                    if not trades:
                        lines.append("No closed trades today")
                    else:
                        wins = [t for t in trades if t.pnl >= 0]
                        losses = [t for t in trades if t.pnl < 0]
                        total_pnl = sum(t.pnl for t in trades)
                        sign = "+" if total_pnl >= 0 else ""
                        lines.append(f"Trades: {len(trades)} (W:{len(wins)} L:{len(losses)})")
                        lines.append(f"Win rate: {len(wins)/len(trades)*100:.0f}%")
                        lines.append(f"P&L: {sign}£{total_pnl:.2f}")
                        for t in trades:
                            s2 = "+" if t.pnl >= 0 else ""
                            emoji = "✅" if t.pnl >= 0 else "❌"
                            lines.append(f"{emoji} {t.instrument.replace('_','/')} {s2}£{t.pnl:.2f}")
            except Exception as e:
                lines.append(f"Error: {e}")
        else:
            lines.append("Database not connected")
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return ("🤖 AtlasFX Bot Commands\n"
                "─────────────────\n"
                "/status — account & open trades\n"
                "/trades — last 8 closed trades\n"
                "/daily — today's P&L report\n"
                "/pairs — active trading pairs\n"
                "/close GBPUSD — close a position\n"
                "/pause — pause new signals\n"
                "/resume — resume trading\n"
                "/help — this menu\n\n"
                "Or just talk to me in plain English!\n"
                "e.g. 'How is my GBP/USD trade doing?'\n"
                "     'Should I close the EUR/USD?'\n"
                "     'How was this week?'")

    # ── TRADE NOTIFICATION METHODS ──────────────────────────────────────

    def trade_opened(self, instrument, direction, entry, sl, tp, units,
                     strategy, risk_pct, confidence=0.7, adx=0, asian_range_pips=0):
        pair = instrument.replace("_", "/")
        is_jpy = "JPY" in instrument or "XAU" in instrument
        d = 3 if is_jpy else 5
        pip = 0.01 if is_jpy else 0.0001
        rr = round(abs(tp - entry) / abs(sl - entry), 2) if abs(sl - entry) > 0 else 0
        sl_pips = round(abs(entry - sl) / pip, 1)
        tp_pips = round(abs(tp - entry) / pip, 1)
        score = min(10, max(1, round(confidence * 10)))
        bar = conf_bar(score)
        label = conf_label(score)
        strat = strategy.replace("_V1", "").replace("_", " ")
        arrow = "📈" if direction == "BUY" else "📉"

        msg = (f"{arrow} TRADE OPENED\n"
               f"━━━━━━━━━━━━━━━━━━━━━\n"
               f"{pair} — {direction}\n"
               f"Strategy: {strat}\n\n"
               f"Entry:  {round(entry, d)}\n"
               f"Stop:   {round(sl, d)} ({sl_pips}p)\n"
               f"Target: {round(tp, d)} ({tp_pips}p)\n"
               f"R:R: 1:{rr} | Risk: {risk_pct}%\n\n"
               f"Confidence: {score}/10 — {label}\n"
               f"{bar}\n"
               f"━━━━━━━━━━━━━━━━━━━━━\n"
               f"{datetime.utcnow().strftime('%H:%M UTC')}")
        if asian_range_pips > 0:
            msg += f"\nRange: {asian_range_pips}p | ADX: {round(adx, 1)}"
        self.send(msg, parse_mode="")

    def trade_update(self, instrument, direction, entry, current, sl, tp,
                     pnl_pips, adx=0, close_callback=None):
        pair = instrument.replace("_", "/")
        is_jpy = "JPY" in instrument or "XAU" in instrument
        d = 3 if is_jpy else 5
        pip = 0.01 if is_jpy else 0.0001
        dist_sl = abs(current - sl) / pip
        dist_tp = abs(tp - current) / pip
        score = confidence_score(direction=direction, entry=entry,
                                  current=current, sl=sl, tp=tp, adx=adx)
        bar = conf_bar(score)
        label = conf_label(score)
        pnl_str = (f"+{pnl_pips:.1f}" if pnl_pips >= 0 else f"{pnl_pips:.1f}")
        progress_pct = ((current - entry) if direction == "BUY" else (entry - current)) / abs(tp - entry) * 100 if tp != entry else 0

        if progress_pct >= 75: status = "Approaching TP — looking strong 🎯"
        elif progress_pct >= 50: status = "Good progress toward TP 📈"
        elif progress_pct >= 25: status = "Moving in right direction"
        elif progress_pct >= -20: status = "Consolidating near entry — normal ORB behaviour"
        elif progress_pct >= -40: status = "Pulling back — watching key levels"
        else: status = "Under pressure — monitor closely ⚠️"

        arrow = "📈" if direction == "BUY" else "📉"
        msg = (f"{arrow} TRADE UPDATE — {pair}\n"
               f"━━━━━━━━━━━━━━━━━━━━━\n"
               f"{direction} | ADX: {round(adx, 0)}\n"
               f"Current: {round(current, d)}\n"
               f"P&L: {pnl_str} pips ({round(progress_pct, 0):.0f}% to TP)\n"
               f"To SL: {dist_sl:.1f}p | To TP: {dist_tp:.1f}p\n\n"
               f"Status: {status}\n\n"
               f"Confidence: {score}/10 — {label}\n"
               f"{bar}\n"
               f"━━━━━━━━━━━━━━━━━━━━━\n"
               f"{datetime.utcnow().strftime('%H:%M UTC')}")

        if score < 4:
            msg += (f"\n⛔ LOW CONFIDENCE WARNING\n"
                    f"Price threatening stop loss.\n"
                    f"Say 'close {pair.replace('/','').lower()}' to exit now.")
            log.warning("telegram_low_confidence", instrument=instrument, score=score)

        self.send(msg, parse_mode="")
        return score

    def trade_closed(self, instrument, direction, pnl, r_multiple, reason,
                     entry=0, exit_price=0, pnl_pips=0):
        pair = instrument.replace("_", "/")
        is_win = pnl >= 0
        is_jpy = "JPY" in instrument or "XAU" in instrument
        d = 3 if is_jpy else 5
        emoji = "🏆" if is_win else "💔"
        result = "WIN" if is_win else "LOSS"
        sign = "+" if pnl >= 0 else ""
        r_sign = "+" if r_multiple >= 0 else ""
        reason_clean = reason.replace("_", " ").title()

        msg = (f"{emoji} TRADE CLOSED — {result}\n"
               f"━━━━━━━━━━━━━━━━━━━━━\n"
               f"{pair} — {direction}\n")
        if entry and exit_price:
            msg += f"Entry: {round(entry, d)} → Exit: {round(exit_price, d)}\n"
        msg += (f"P&L: {sign}£{round(pnl, 2)}\n"
                f"R: {r_sign}{round(r_multiple, 2)}R\n"
                f"Reason: {reason_clean}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{datetime.utcnow().strftime('%H:%M UTC')}")
        self.send(msg, parse_mode="")

    def sl_moved(self, instrument, old_sl, new_sl, profit_r):
        pair = instrument.replace("_", "/")
        is_jpy = "JPY" in instrument
        d = 3 if is_jpy else 5
        self.send(f"🔒 STOP MOVED — {pair}\n"
                  f"SL: {round(old_sl, d)} → {round(new_sl, d)}\n"
                  f"Locked: +{round(profit_r, 2)}R", parse_mode="")

    def daily_report(self, date, trades, wins, losses, pnl, win_rate, balance):
        sign = "+" if pnl >= 0 else ""
        self.send(f"📊 DAILY REPORT — {date}\n"
                  f"━━━━━━━━━━━━━━━━━━━━━\n"
                  f"Trades: {trades} (W:{wins} L:{losses})\n"
                  f"Win Rate: {round(win_rate, 1)}%\n"
                  f"P&L: {sign}£{round(pnl, 2)}\n"
                  f"Balance: £{round(balance, 2)}", parse_mode="")

    def agent_started(self):
        self.send(f"🚀 AtlasFX Online\n"
                  f"London ORB + NY ORB + EMA Pullback\n"
                  f"27 pairs | 68.9% WR (walk-forward validated)\n"
                  f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", parse_mode="")

    def agent_stopped(self, reason):
        self.send(f"⛔ AtlasFX Stopped\nReason: {reason}", parse_mode="")

    def risk_alert(self, message):
        self.send(f"🚨 RISK ALERT\n{message}", parse_mode="")

    def health_check_failed(self):
        self.send(f"⚠️ Health Check Failed\nVPS: ssh root@158.220.93.163", parse_mode="")
