from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import SYMBOLS, settings
from db import Database
from news_filter import NewsFilter
from signal_engine import SignalEngine
from vip_manager import VIPManager

log = logging.getLogger(__name__)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Signal", callback_data="menu_signal"), InlineKeyboardButton("💎 VIP Status", callback_data="menu_vip")],
        [InlineKeyboardButton("💰 Risk Calculator", callback_data="menu_risk"), InlineKeyboardButton("🗓 Calendar", callback_data="menu_calendar")],
    ])


class UserHandlers:
    def __init__(self, db: Database, engine: SignalEngine, news: NewsFilter, vip: VIPManager) -> None:
        self.db = db
        self.engine = engine
        self.news = news
        self.vip = vip

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or not update.message:
            return
        self.db.upsert_user(user.id, user.username, user.first_name)
        await update.message.reply_text(
            "🚀 *Forex & Gold Signal Bot*\n\nChoose an option below. Signals are educational and are not guaranteed.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu(),
        )

    async def signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not self.vip.is_vip(update.effective_user.id if update.effective_user else 0):
            await update.message.reply_text("💎 Full signal access is VIP-only. Use /vip_status to check your membership.")
            return
        symbol = context.args[0].upper() if context.args else "XAUUSD"
        if symbol not in SYMBOLS:
            await update.message.reply_text("Unsupported symbol. Use: XAUUSD, EURUSD, GBPUSD, USDJPY, AUDUSD")
            return
        blocked, event = await self.news.is_blocked(symbol)
        if blocked:
            reason = f"High-impact event: {event.title}" if event else "Economic calendar unavailable/stale"
            await update.message.reply_text(f"🛑 Signal blocked. {reason}")
            return
        try:
            signal = await __import__("asyncio").to_thread(self.engine.generate_signal, symbol)
            if not signal:
                await update.message.reply_text(f"No aligned signal for {symbol} across 15M/1H/4H.")
                return
            text = self._signal_text(signal)
            await update.message.reply_text(text)
        except Exception as exc:
            log.exception("Signal command failed")
            await update.message.reply_text(f"Signal engine unavailable: {exc.__class__.__name__}")

    async def risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        try:
            balance = float(context.args[0]) if context.args else 0
            if balance <= 0:
                raise ValueError
            risk = balance * settings.risk_percent_default / 100
            await update.message.reply_text(
                f"💰 Balance: {balance:,.2f}\nRisk @ {settings.risk_percent_default:.1f}%: {risk:,.2f}\n\nThis is a risk budget, not a position-size guarantee."
            )
        except ValueError:
            await update.message.reply_text("Usage: /risk <balance>")

    async def calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await self.news.refresh()
        if not self.news.feed_ok:
            await update.message.reply_text("⚠️ Economic calendar feed is unavailable. Signal generation remains blocked by safety policy.")
            return
        if not self.news._events:
            await update.message.reply_text("No high-impact events available from the configured calendar feed.")
            return
        lines = ["🗓 *High-impact calendar*\n"]
        for event in self.news._events[:10]:
            lines.append(f"• {event.event_time:%d %b %H:%M UTC} — {event.currency or 'GLOBAL'} — {event.title}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def vip_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message and update.effective_user:
            await update.message.reply_text(self.vip.status_text(update.effective_user.id))

    async def callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        await query.answer()
        if query.data == "menu_vip" and query.from_user:
            await query.edit_message_text(self.vip.status_text(query.from_user.id), reply_markup=main_menu())
        elif query.data == "menu_signal":
            await query.edit_message_text("Use /signal XAUUSD (or EURUSD, GBPUSD, USDJPY, AUDUSD).", reply_markup=main_menu())
        elif query.data == "menu_risk":
            await query.edit_message_text("Use /risk 1000 to calculate the configured risk budget.", reply_markup=main_menu())
        elif query.data == "menu_calendar":
            await query.edit_message_text("Use /calendar to fetch high-impact events.", reply_markup=main_menu())

    @staticmethod
    def _signal_text(signal) -> str:
        tf = " | ".join(f"{s.timeframe}:{s.direction}" for s in signal.states)
        return (
            f"📈 *{signal.symbol} {signal.direction}*\n\n"
            f"Entry: `{signal.entry}`\nSL: `{signal.sl}`\nTP1: `{signal.tp1}`\nTP2: `{signal.tp2}`\n"
            f"R:R: 1:{signal.rr:.1f}\n\nAlignment: {tf}"
        )
