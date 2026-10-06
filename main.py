from __future__ import annotations

import asyncio
import logging

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

from admin_handlers import AdminHandlers
from bot_handlers import UserHandlers
from chart_generator import ChartGenerator
from config import settings, validate_settings, SYMBOLS
from db import Database
from news_filter import NewsFilter
from signal_engine import SignalEngine
from tracker import TradeTracker
from vip_manager import VIPManager

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


class SignalBotApp:
    def __init__(self) -> None:
        self.db = Database()
        self.engine = SignalEngine()
        self.news = NewsFilter()
        self.vip = VIPManager(self.db)
        self.chart = ChartGenerator()
        self.tracker = TradeTracker(self.db, self.engine)
        self.user = UserHandlers(self.db, self.engine, self.news, self.vip)
        self.admin = AdminHandlers(self.db)

    async def scanner_job(self, context) -> None:
        # Signal creation is deliberately separated from trade tracking.
        # It runs less frequently to avoid hammering public TradingView endpoints.
        for symbol in SYMBOLS:
            try:
                if self.db.get_open_trade_for_symbol(symbol):
                    continue
                if self.db.recent_signal_exists(symbol, settings.signal_cooldown_minutes):
                    continue
                blocked, event = await self.news.is_blocked(symbol)
                if blocked:
                    continue
                signal = await asyncio.to_thread(self.engine.generate_signal, symbol)
                if not signal:
                    continue
                image = await self.chart.render(signal)
                caption = (
                    f"🚨 *VIP SIGNAL — {signal.symbol} {signal.direction}*\n\n"
                    f"Entry: `{signal.entry}`\nSL: `{signal.sl}`\nTP1: `{signal.tp1}`\nTP2: `{signal.tp2}`\n"
                    f"R:R: 1:{signal.rr:.1f}\n\n"
                    "⚠️ Manage risk. Educational signal only."
                )
                msg = await context.bot.send_photo(settings.vip_channel_id, image, caption=caption, parse_mode="Markdown")
                teaser = await context.bot.send_message(
                    settings.public_channel_id,
                    f"🔥 NEW VIP SETUP: {signal.symbol} {signal.direction}\nA high-confidence multi-timeframe setup just dropped. Join VIP for Entry/SL/TPs + chart."
                )
                self.db.create_trade(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    entry=signal.entry,
                    sl=signal.sl,
                    tp1=signal.tp1,
                    tp2=signal.tp2,
                    rr=signal.rr,
                    risk_percent=settings.risk_percent_default,
                    entry_message_id=msg.message_id,
                    teaser_message_id=teaser.message_id,
                    notes="15M/1H/4H aligned",
                )
                self.db.log_event("signal_created", f"{signal.symbol} {signal.direction}")
            except Exception:
                log.exception("Signal scan failed for %s", symbol)

    async def tracker_job(self, context) -> None:
        await self.tracker.scan(context.bot)

    async def vip_job(self, context) -> None:
        await self.vip.expiry_scan(context.bot, settings.admin_ids)

    def build(self):
        application = ApplicationBuilder().token(settings.bot_token).build()
        application.add_handler(CommandHandler("start", self.user.start))
        application.add_handler(CommandHandler("signal", self.user.signal))
        application.add_handler(CommandHandler("risk", self.user.risk))
        application.add_handler(CommandHandler("calendar", self.user.calendar))
        application.add_handler(CommandHandler("vip_status", self.user.vip_status))
        application.add_handler(CallbackQueryHandler(self.user.callbacks))

        application.add_handler(CommandHandler("grantvip", self.admin.grantvip))
        application.add_handler(CommandHandler("revokevip", self.admin.revokevip))
        application.add_handler(CommandHandler("broadcast", self.admin.broadcast))
        application.add_handler(CommandHandler("stats", self.admin.stats))
        application.add_handler(CommandHandler("export_journal", self.admin.export_journal))
        application.add_handler(CommandHandler("ping", self.admin.ping))

        jq = application.job_queue
        if jq is None:
            raise RuntimeError('JobQueue unavailable. Install python-telegram-bot[job-queue].')
        jq.run_repeating(self.tracker_job, interval=settings.scan_seconds, first=10, name="trade-tracker")
        jq.run_repeating(self.scanner_job, interval=settings.signal_scan_seconds, first=20, name="signal-scanner")
        jq.run_repeating(self.vip_job, interval=settings.vip_expiry_scan_seconds, first=30, name="vip-expiry")
        return application


def main() -> None:
    validate_settings()
    app = SignalBotApp().build()
    log.info("Starting Telegram signal bot")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
