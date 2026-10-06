from __future__ import annotations

import asyncio
import email.utils
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsEvent:
    title: str
    event_time: datetime
    impact: str
    currency: str = ""


class NewsFilter:
    HIGH_IMPACT = re.compile(r"\b(NFP|NON[- ]?FARM|CPI|FOMC|FEDERAL RESERVE|INTEREST RATE|RATE DECISION|PCE|GDP|ECB|BOE|BOJ|RBA|RBNZ)\b", re.I)

    def __init__(self) -> None:
        self._events: list[NewsEvent] = []
        self._last_refresh: datetime | None = None
        self._feed_ok = False

    async def refresh(self) -> None:
        def fetch() -> list[NewsEvent]:
            req = urllib.request.Request(
                settings.news_rss_url,
                headers={"User-Agent": "Mozilla/5.0 signal-bot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read()
            root = ET.fromstring(raw)
            result: list[NewsEvent] = []
            for item in root.iter():
                if item.tag.lower().endswith("item"):
                    title = self._child_text(item, "title") or ""
                    description = self._child_text(item, "description") or ""
                    date_text = self._child_text(item, "pubDate") or self._child_text(item, "date") or ""
                    time_text = self._child_text(item, "time") or ""
                    impact = self._child_text(item, "impact") or self._child_text(item, "importance") or ""
                    currency = self._child_text(item, "currency") or ""
                    if not self.HIGH_IMPACT.search(f"{title} {description}") and impact.lower() not in {"high", "3"}:
                        continue
                    dt = self._parse_datetime(date_text or time_text)
                    if dt:
                        result.append(NewsEvent(title.strip() or description.strip(), dt, impact or "high", currency))
            return result

        try:
            self._events = await asyncio.to_thread(fetch)
            self._last_refresh = datetime.now(timezone.utc)
            self._feed_ok = True
        except Exception:
            log.exception("Economic calendar refresh failed")
            self._events = []
            self._feed_ok = False
            self._last_refresh = datetime.now(timezone.utc)

    @staticmethod
    def _child_text(parent: ET.Element, suffix: str) -> str | None:
        for child in list(parent):
            if child.tag.lower().endswith(suffix.lower()):
                return child.text
        return None

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        value = value.strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            return email.utils.parsedate_to_datetime(value).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
        # Common Forex Factory XML form: YYYY-MM-DD HH:MM:SS
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
            except ValueError:
                continue
        return None

    @property
    def feed_ok(self) -> bool:
        return self._feed_ok

    async def is_blocked(self, symbol: str) -> tuple[bool, NewsEvent | None]:
        now = datetime.now(timezone.utc)
        if self._last_refresh is None or now - self._last_refresh > timedelta(minutes=15):
            await self.refresh()
        if settings.news_fail_closed and not self._feed_ok:
            return True, None
        # Fail closed if the feed is stale for more than one hour.
        if settings.news_fail_closed and (now - self._last_refresh) > timedelta(hours=1):
            return True, None
        currencies = {"XAUUSD": {"USD"}, "EURUSD": {"EUR", "USD"}, "GBPUSD": {"GBP", "USD"}, "USDJPY": {"USD", "JPY"}, "AUDUSD": {"AUD", "USD"}}.get(symbol, {"USD"})
        guard = timedelta(minutes=settings.news_guard_minutes)
        for event in self._events:
            if event.currency and event.currency.upper() not in currencies:
                continue
            if event.event_time - guard <= now <= event.event_time + guard:
                return True, event
        return False, None
