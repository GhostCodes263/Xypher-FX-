import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    bot_token: str
    vip_channel_id: int
    public_channel_id: int
    admin_ids: tuple[int, ...]
    database_path: str
    timezone: str
    scan_seconds: int
    signal_scan_seconds: int
    vip_expiry_scan_seconds: int
    tv_timeout: int
    news_rss_url: str
    news_guard_minutes: int
    news_fail_closed: bool
    ohlc_url_template: str
    chart_bars: int
    chart_timeout: int
    atr_fallback_pct: float
    min_rr: float
    max_open_trades_per_symbol: int
    signal_cooldown_minutes: int
    risk_percent_default: float
    log_level: str


ADMIN_IDS = tuple(
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
)

settings = Settings(
    bot_token=os.getenv("BOT_TOKEN", ""),
    vip_channel_id=_env_int("VIP_CHANNEL_ID", 0),
    public_channel_id=_env_int("PUBLIC_CHANNEL_ID", 0),
    admin_ids=ADMIN_IDS,
    database_path=os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "bot.sqlite3")),
    timezone=os.getenv("TIMEZONE", "Africa/Harare"),
    scan_seconds=max(30, _env_int("SCAN_SECONDS", 60)),
    signal_scan_seconds=max(60, _env_int("SIGNAL_SCAN_SECONDS", 300)),
    vip_expiry_scan_seconds=max(300, _env_int("VIP_EXPIRY_SCAN_SECONDS", 3600)),
    tv_timeout=max(5, _env_int("TV_TIMEOUT", 15)),
    news_rss_url=os.getenv(
        "NEWS_RSS_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    ),
    news_guard_minutes=max(1, _env_int("NEWS_GUARD_MINUTES", 30)),
    news_fail_closed=_env_bool("NEWS_FAIL_CLOSED", True),
    ohlc_url_template=os.getenv(
        "OHLC_URL_TEMPLATE",
        "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=5d",
    ),
    chart_bars=max(50, _env_int("CHART_BARS", 120)),
    chart_timeout=max(5, _env_int("CHART_TIMEOUT", 15)),
    atr_fallback_pct=float(os.getenv("ATR_FALLBACK_PCT", "0.0025")),
    min_rr=float(os.getenv("MIN_RR", "2.0")),
    max_open_trades_per_symbol=max(1, _env_int("MAX_OPEN_TRADES_PER_SYMBOL", 1)),
    signal_cooldown_minutes=max(1, _env_int("SIGNAL_COOLDOWN_MINUTES", 45)),
    risk_percent_default=float(os.getenv("RISK_PERCENT_DEFAULT", "1.0")),
    log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
)

SYMBOLS = {
    "XAUUSD": {"tv": "OANDA:XAUUSD", "yahoo": "GC=F", "digits": 2, "pip_size": 0.01},
    "EURUSD": {"tv": "OANDA:EURUSD", "yahoo": "EURUSD=X", "digits": 5, "pip_size": 0.0001},
    "GBPUSD": {"tv": "OANDA:GBPUSD", "yahoo": "GBPUSD=X", "digits": 5, "pip_size": 0.0001},
    "USDJPY": {"tv": "OANDA:USDJPY", "yahoo": "JPY=X", "digits": 3, "pip_size": 0.01},
    "AUDUSD": {"tv": "OANDA:AUDUSD", "yahoo": "AUDUSD=X", "digits": 5, "pip_size": 0.0001},
}

TV_INTERVALS = {"15m": "15m", "1h": "1h", "4h": "4h"}


def validate_settings() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    if not settings.vip_channel_id:
        raise RuntimeError("VIP_CHANNEL_ID is required")
    if not settings.public_channel_id:
        raise RuntimeError("PUBLIC_CHANNEL_ID is required")
    if not settings.admin_ids:
        raise RuntimeError("ADMIN_IDS must contain at least one Telegram user ID")
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
