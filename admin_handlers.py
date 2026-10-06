from __future__ import annotations

import io
import logging

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import settings
from db import Database

log = logging.getLogger(__name__)


class AdminHandlers:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _is_admin(self, update: Update) -> bool:
        return bool(update.effective_user and update.effective_user.id in settings.admin_ids)

    async def grantvip(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update) or not update.message:
            return
        if len(context.args) != 2:
            await update.message.reply_text("Usage: /grantvip <user_id> <days>")
            return
        try:
            user_id, days = int(context.args[0]), int(context.args[1])
            if days <= 0:
                raise ValueError
            row = self.db.grant_vip(user_id, days)
            await update.message.reply_text(f"VIP granted to {user_id} until {row['end_at']}.")
        except ValueError:
            await update.message.reply_text("Invalid user ID or days.")

    async def revokevip(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update) or not update.message:
            return
        if len(context.args) != 1:
            await update.message.reply_text("Usage: /revokevip <user_id>")
            return
        try:
            user_id = int(context.args[0])
            ok = self.db.revoke_vip(user_id)
            await update.message.reply_text("VIP revoked." if ok else "No active VIP found.")
        except ValueError:
            await update.message.reply_text("Invalid user ID.")

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update) or not update.message:
            return
        message = " ".join(context.args).strip()
        if not message:
            await update.message.reply_text("Usage: /broadcast <message>")
            return
        sent = 0
        # Broadcast only to known users; Telegram does not permit arbitrary user discovery.
        with self.db._lock, self.db._connect() as conn:
            users = conn.execute("SELECT user_id FROM users").fetchall()
        for row in users:
            try:
                await context.bot.send_message(row["user_id"], message)
                sent += 1
            except Exception:
                continue
        await update.message.reply_text(f"Broadcast complete: {sent}/{len(users)} delivered.")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update) or not update.message:
            return
        s = self.db.stats()
        await update.message.reply_text(
            "📊 *Bot stats*\n"
            f"Trades: {s['trades']}\nOpen: {s['open']}\nTP1: {s['tp1']}\nTP2: {s['tp2']}\nSL: {s['sl']}\nInvalidated: {s['invalidated']}\nVIP: {s['vip']}\nPips: {s['pips']:+.1f}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def export_journal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update) or not update.message:
            return
        data = self.db.export_trades_csv()
        await update.message.reply_document(InputFile(io.BytesIO(data), filename="trades.csv"))

    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._is_admin(update) and update.message:
            await update.message.reply_text("pong 🟢")
