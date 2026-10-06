# Telegram Forex & Gold Signal Bot

A modular async Telegram signal platform for XAUUSD, EURUSD, GBPUSD, USDJPY and AUDUSD. It uses TradingView's unofficial `tradingview-ta` wrapper for technical summaries, a public no-key OHLC endpoint for chart candles, SQLite for persistence, and Telegram's JobQueue/APScheduler for background work.

## Important operational caveat

This project does **not** have a guaranteed unlimited/no-rate-limit market-data source. `tradingview-ta` is an unofficial wrapper around TradingView's scanner endpoints and public endpoints can throttle, reject, or change. The bot therefore uses timeouts, reduced scan frequency, caching, and fail-safe behavior. Do not represent the feed as a guaranteed SLA.

TradingView-T​​A documents `TA_Handler`, forex screener usage, `FX_IDC`, supported intervals, and the indicator fields used here. The wrapper's source also exposes EMA20/EMA50, RSI, MACD and close fields. See the upstream project before deploying updates.

## Features

- 15M/1H/4H alignment using price vs EMA20/EMA50, RSI and MACD.
- ATR-based dynamic SL, TP1 at 1R and TP2 at 2R.
- Matplotlib 15M candlestick charts.
- High-impact news guard around NFP/CPI/FOMC/rate decisions and related events.
- VIP channel receives complete signals.
- Public channel receives teasers and result updates.
- 60-second open-trade tracker.
- TP1 breakeven alert, TP2 celebration, SL result and early TA invalidation.
- SQLite VIP subscriptions and trade journal.
- Admin commands for VIP, broadcast, statistics, CSV export and ping.
- Mobile-friendly inline menu.

## Telegram setup

1. Create a bot with BotFather and put the token in `.env`.
2. Add the bot as an administrator in both channels.
3. Give it permission to post messages/photos.
4. Put the numeric channel IDs in `VIP_CHANNEL_ID` and `PUBLIC_CHANNEL_ID`.
5. Put your Telegram numeric user ID(s) in `ADMIN_IDS`.
6. Copy `.env.example` to `.env` and fill the values.

## Local run

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
# .venv\\Scripts\\activate
pip install -r requirements.txt
python main.py
```

Python 3.10+ is recommended.

## Commands

### Users

- `/start`
- `/signal XAUUSD`
- `/risk 1000`
- `/calendar`
- `/vip_status`

### Admins

- `/grantvip <user_id> <days>`
- `/revokevip <user_id>`
- `/broadcast <message>`
- `/stats`
- `/export_journal`
- `/ping`

## Signal logic

A signal is emitted only when all three timeframes have the same direction:

**BUY:** close > EMA20 > EMA50, RSI >= 50 and MACD >= signal.

**SELL:** close < EMA20 < EMA50, RSI <= 50 and MACD <= signal.

The 15M ATR determines risk distance. If ATR is unavailable, a configurable percentage fallback is used. TP1 is 1R and TP2 is 2R.

## News guard

The default feed is a Forex Factory-compatible XML calendar URL. Configure `NEWS_RSS_URL` to another XML/RSS source if needed. The parser looks for NFP/non-farm, CPI, FOMC/Federal Reserve, rate decisions, PCE, GDP and major central-bank events. The default behavior is fail-closed when the calendar is unavailable or stale.

Because free calendar feeds are not guaranteed APIs, verify the feed in your deployment environment before trusting the guard with real money.

## Tracking semantics

The tracker uses the 15M TradingView close as its current price. It checks SL, TP1 and TP2 on each scan. Once TP1 is touched it alerts users to move SL to breakeven. If the 15M TA reverses against the open trade, the trade is marked `INVALIDATED` and an early-exit alert is sent.

This is a signal journal, not a broker execution engine. No orders are opened or modified at a broker.

## Deployment

### Render

Use a Python background worker rather than a web service unless your plan requires an HTTP endpoint. Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
python main.py
```

Set the environment variables from `.env.example` in the Render dashboard. Attach persistent storage for the SQLite database if you need the journal/subscriptions to survive redeploys.

### PythonAnywhere

Create a virtualenv, install `requirements.txt`, set environment variables, and run `python main.py` as a long-running task/console process. SQLite is simplest when the bot runs as a single process.

## Production recommendations

- Run exactly one bot worker against a single SQLite database.
- Back up `data/bot.sqlite3` regularly.
- Keep bot token out of GitHub.
- Restrict admin IDs carefully.
- Monitor TradingView HTTP failures and calendar failures.
- Do not advertise the market feed as unlimited or guaranteed.
- Before using real capital, paper-test the signal logic and independently validate price, news and execution assumptions.
- Consider replacing the public data sources with a paid broker/data feed when reliability becomes business-critical.

## License

Use and modify at your own risk. Trading is risky; this software does not provide financial advice and does not guarantee profitable signals.
