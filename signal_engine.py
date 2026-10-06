from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from tradingview_ta import TA_Handler, Interval

from config import SYMBOLS, settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeframeState:
    timeframe: str
    direction: str
    close: float
    ema20: float
    ema50: float
    rsi: float
    macd: float
    macd_signal: float
    atr: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    atr: float
    states: tuple[TimeframeState, ...]


class SignalEngine:
    def __init__(self) -> None:
        self._price_cache: dict[str, float] = {}

    @staticmethod
    def _indicator(data: dict[str, Any], key: str) -> float | None:
        value = data.get(key)
        if value is None:
            return None
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    def analyze_timeframe(self, symbol: str, timeframe: str) -> TimeframeState:
        if symbol not in SYMBOLS:
            raise ValueError(f"Unsupported symbol: {symbol}")
        interval = {"15m": Interval.INTERVAL_15_MINUTES, "1h": Interval.INTERVAL_1_HOUR, "4h": Interval.INTERVAL_4_HOURS}[timeframe]
        tv_symbol = SYMBOLS[symbol]["tv"].split(":", 1)[1]
        handler = TA_Handler(
            symbol=tv_symbol,
            screener="forex",
            exchange="OANDA",
            interval=interval,
            timeout=settings.tv_timeout,
        )
        analysis = handler.get_analysis()
        d = analysis.indicators
        close = self._indicator(d, "close")
        ema20 = self._indicator(d, "EMA20")
        ema50 = self._indicator(d, "EMA50")
        rsi = self._indicator(d, "RSI")
        macd = self._indicator(d, "MACD.macd")
        macd_signal = self._indicator(d, "MACD.signal")
        atr = self._indicator(d, "ATR") or 0.0
        if any(v is None for v in (close, ema20, ema50, rsi, macd, macd_signal)):
            raise RuntimeError(f"Incomplete TradingView data for {symbol} {timeframe}")
        self._price_cache[symbol] = close
        bullish = close > ema20 > ema50 and rsi >= 50 and macd >= macd_signal
        bearish = close < ema20 < ema50 and rsi <= 50 and macd <= macd_signal
        direction = "BUY" if bullish else "SELL" if bearish else "NEUTRAL"
        return TimeframeState(timeframe, direction, close, ema20, ema50, rsi, macd, macd_signal, atr)

    def multi_timeframe(self, symbol: str) -> tuple[TimeframeState, ...]:
        states = tuple(self.analyze_timeframe(symbol, tf) for tf in ("15m", "1h", "4h"))
        return states

    def generate_signal(self, symbol: str) -> Signal | None:
        states = self.multi_timeframe(symbol)
        directions = {s.direction for s in states}
        if directions != {"BUY"} and directions != {"SELL"}:
            return None
        direction = states[0].direction
        entry = states[0].close
        atr = states[0].atr
        if atr <= 0:
            atr = entry * settings.atr_fallback_pct
        # A 1x ATR protective stop gives TP1=1R and TP2=2R by construction.
        risk_distance = max(atr, entry * settings.atr_fallback_pct)
        if direction == "BUY":
            sl = entry - risk_distance
            tp1 = entry + risk_distance
            tp2 = entry + 2 * risk_distance
        else:
            sl = entry + risk_distance
            tp1 = entry - risk_distance
            tp2 = entry - 2 * risk_distance
        rr = abs(tp2 - entry) / abs(entry - sl)
        digits = SYMBOLS[symbol]["digits"]
        return Signal(symbol, direction, round(entry, digits), round(sl, digits), round(tp1, digits), round(tp2, digits), round(rr, 2), risk_distance, states)

    def current_price(self, symbol: str) -> float:
        # The 15m TradingView close is used as the bot's no-key live-price source.
        state = self.analyze_timeframe(symbol, "15m")
        return state.close

    def reversal(self, symbol: str, direction: str) -> bool:
        state = self.analyze_timeframe(symbol, "15m")
        return (direction == "BUY" and state.direction == "SELL") or (direction == "SELL" and state.direction == "BUY")
