from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Bot

from config import SYMBOLS, settings
from db import Database
from signal_engine import SignalEngine

log = logging.getLogger(__name__)


class TradeTracker:
    def __init__(self, db: Database, engine: SignalEngine) -> None:
        self.db = db
        self.engine = engine

    @staticmethod
    def pip_count(symbol: str, direction: str, entry: float, price: float) -> float:
        pip = SYMBOLS[symbol]["pip_size"]
        move = (price - entry) if direction == "BUY" else (entry - price)
        return move / pip

    async def scan(self, bot: Bot) -> None:
        trades = self.db.get_open_trades()
        for trade in trades:
            try:
                price = await __import__("asyncio").to_thread(self.engine.current_price, trade["symbol"])
                self.db.update_trade(trade["id"], last_price=price)
                direction = trade["direction"]
                if direction == "BUY":
                    hit_sl = price <= trade["sl"]
                    hit_tp1 = price >= trade["tp1"]
                    hit_tp2 = price >= trade["tp2"]
                else:
                    hit_sl = price >= trade["sl"]
                    hit_tp1 = price <= trade["tp1"]
                    hit_tp2 = price <= trade["tp2"]

                if hit_sl and not trade["tp2_hit"]:
                    pips = self.pip_count(trade["symbol"], direction, trade["entry"], price)
                    self.db.update_trade(trade["id"], status="SL", closed_at=datetime.now(timezone.utc).isoformat(), pnl_pips=pips)
                    await self._broadcast(bot, f"🛑 {trade['symbol']} {direction} SL HIT\nResult: {pips:+.1f} pips")
                    continue

                if hit_tp1 and not trade["tp1_hit"]:
                    self.db.update_trade(trade["id"], tp1_hit=1, breakeven_alert_sent=1)
                    await self._broadcast(bot, f"✅ {trade['symbol']} TP1 HIT\nMove SL to BREAKEVEN now.\nCurrent result: {self.pip_count(trade['symbol'], direction, trade['entry'], price):+.1f} pips")

                if hit_tp2:
                    pips = self.pip_count(trade["symbol"], direction, trade["entry"], price)
                    self.db.update_trade(trade["id"], status="TP2", tp1_hit=1, tp2_hit=1, closed_at=datetime.now(timezone.utc).isoformat(), pnl_pips=pips)
                    await self._broadcast(bot, f"🏆 {trade['symbol']} TP2 HIT\nProfit: {pips:+.1f} pips 🎯")
                    continue

                if await __import__("asyncio").to_thread(self.engine.reversal, trade["symbol"], direction):
                    if not trade["invalidation_alert_sent"]:
                        self.db.update_trade(trade["id"], invalidation_alert_sent=1, status="INVALIDATED", closed_at=datetime.now(timezone.utc).isoformat(), notes="15m TA reversal")
                        await self._broadcast(bot, f"⚠️ {trade['symbol']} EARLY INVALIDATION\n15M trend reversed. Exit the trade early and protect capital.")
            except Exception:
                log.exception("Trade tracking failed for trade %s", trade["id"])

    async def _broadcast(self, bot: Bot, text: str) -> None:
        self.db.log_event("trade_update", text)
        await bot.send_message(settings.vip_channel_id, text)
        await bot.send_message(settings.public_channel_id, text)
