from __future__ import annotations

import asyncio
import io
import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from config import SYMBOLS, settings
from signal_engine import Signal

log = logging.getLogger(__name__)


class ChartGenerator:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[datetime, list[dict[str, float]]]] = {}

    async def _fetch_ohlc(self, symbol: str) -> list[dict[str, float]]:
        ticker = SYMBOLS[symbol]["yahoo"]
        url = settings.ohlc_url_template.format(ticker=ticker)

        def fetch() -> list[dict[str, float]]:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 signal-bot/1.0"})
            with urllib.request.urlopen(req, timeout=settings.chart_timeout) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            result = payload["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            q = result["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(timestamps):
                vals = {k: q.get(k, [None] * len(timestamps))[i] for k in ("open", "high", "low", "close")}
                if all(v is not None for v in vals.values()):
                    rows.append({"timestamp": float(ts), **{k: float(v) for k, v in vals.items()}})
            return rows[-settings.chart_bars :]

        now = datetime.now(timezone.utc)
        cached = self._cache.get(symbol)
        if cached and now - cached[0] < __import__("datetime").timedelta(seconds=45):
            return cached[1]
        rows = await asyncio.to_thread(fetch)
        self._cache[symbol] = (now, rows)
        return rows

    async def render(self, signal: Signal) -> io.BytesIO:
        rows = await self._fetch_ohlc(signal.symbol)
        if len(rows) < 10:
            raise RuntimeError(f"Not enough OHLC data for {signal.symbol}")
        fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
        width = (rows[1]["timestamp"] - rows[0]["timestamp"]) / 86400 * 0.72
        for row in rows:
            x = datetime.fromtimestamp(row["timestamp"], tz=timezone.utc)
            color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
            ax.plot([x, x], [row["low"], row["high"]], linewidth=0.8, color=color)
            bottom = min(row["open"], row["close"])
            height = max(abs(row["close"] - row["open"]), 1e-9)
            ax.add_patch(Rectangle((mdates.date2num(x) - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.6))

        ax.axhline(signal.entry, label=f"Entry {signal.entry}", linewidth=1.2, color="blue")
        ax.axhline(signal.sl, label=f"SL {signal.sl}", linewidth=1.2, color="red")
        ax.axhline(signal.tp1, label=f"TP1 {signal.tp1}", linewidth=1.2, color="green")
        ax.axhline(signal.tp2, label=f"TP2 {signal.tp2}", linewidth=1.4, color="#00ff00")
        ax.set_title(f"{signal.symbol} • 15M • {signal.direction}")
        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.15)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M", tz=timezone.utc))
        fig.autofmt_xdate()
        ax.legend(loc="upper left", fontsize=8)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        buf.name = f"{signal.symbol}_{signal.direction}.png"
        return buf
