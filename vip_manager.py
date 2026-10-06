from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Bot

from db import Database

log = logging.getLogger(__name__)


class VIPManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    def is_vip(self, user_id: int) -> bool:
        row = self.db.vip_status(user_id)
        return bool(row and row["status"] == "active" and datetime.fromisoformat(row["end_at"]) > datetime.now(timezone.utc))

    def status_text(self, user_id: int) -> str:
        row = self.db.vip_status(user_id)
        if not row or row["status"] != "active":
            return "❌ VIP inactive."
        end = datetime.fromisoformat(row["end_at"]).astimezone(timezone.utc)
        return f"✅ VIP active\nExpires: {end:%Y-%m-%d %H:%M UTC}"

    async def expiry_scan(self, bot: Bot, admin_ids: tuple[int, ...]) -> None:
        expired = self.db.expire_vips()
        for row in expired:
            try:
                await bot.send_message(row["user_id"], "⚠️ Your VIP subscription has expired. Contact an admin to renew.")
            except Exception:
                log.warning("Could not notify expired VIP user %s", row["user_id"])
            self.db.log_event("vip_expired", user_id=row["user_id"])
        expiring = self.db.get_expiring_vips(24)
        for row in expiring:
            try:
                await bot.send_message(row["user_id"], f"⏰ Your VIP subscription expires within 24 hours: {row['end_at']}")
            except Exception:
                pass
            self.db.mark_vip_expiry_notified(row["user_id"])
        for admin_id in admin_ids:
            if expired:
                try:
                    await bot.send_message(admin_id, f"VIP expiry scanner: {len(expired)} subscription(s) expired.")
                except Exception:
                    pass
