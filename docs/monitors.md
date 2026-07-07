# Monitor Reference

Monitors are lightweight, pure-Python watchers that run alongside the agents on every scheduled cycle. Unlike agents they do **not** produce scores or feed the Broker Agent — they observe market conditions and raise alerts for the human in the loop.

| Monitor | File | Trigger |
|---------|------|---------|
| 52-Week Low | `monitors/week52_low.py` | Price makes a new 52-week low, or trades within a configurable band above it |

---

## 52-Week Low Monitor

**File:** `monitors/week52_low.py`
**LLM:** None — pure Python
**Data:** DuckDB `ohlcv` table (primary), `kite.historical_data()` (fallback), live price via the standard kite_client chain (WebSocket cache → REST → error)
**Config:** `monitors.week52_low` in `config.yaml`

### What it does

For each watchlist ticker:

1. Compute the trailing 52-week low as `MIN(low)` over the last `lookback_days` (default 365) from the local `ohlcv` table. If fewer than ~200 daily candles are stored locally (NSE has ~250 trading days/year), fall back to a 1-year `kite.historical_data()` call so an incomplete local history can't masquerade as a yearly low.
2. Fetch the live price.
3. Classify:

| Condition | Alert kind |
|-----------|-----------|
| `last_price ≤ week52_low` | `NEW_52W_LOW` |
| `0 < (last_price − week52_low) / week52_low ≤ proximity_pct` | `NEAR_52W_LOW` |
| Otherwise | No alert |

### Alert delivery

- Row inserted into the `week52_low_alerts` DuckDB table (schema in [`configuration.md`](configuration.md))
- Native macOS notification (if `notify: true`) deep-linking to the dashboard with the ticker highlighted
- Shown on the Watchlist Dashboard alongside the ticker's scores

### Cooldown

A stock sitting at its low would otherwise alert on every one of the three daily runs. After a ticker alerts, it is suppressed for `cooldown_hours` (default 24) — enforced by checking `MAX(triggered_at)` in the alerts table, so the cooldown survives process restarts.

### Running standalone

```bash
# Sweep the full watchlist once
python -m monitors.week52_low

# Check a single ticker
python -m monitors.week52_low --ticker INFY
```

### Error handling

| Failure | Behaviour |
|---------|-----------|
| No local OHLCV and Kite historical fetch fails | Ticker skipped with a warning, no alert |
| Live price unavailable | Ticker skipped with a warning, no alert |
| Any per-ticker exception | Logged with traceback; remaining tickers still checked |

### Design notes

- Alerts are **informational only**. A 52-week low is a context signal, not a buy/sell signal — the Technical Agent already scores oversold conditions (RSI, Bollinger position). Keeping the monitor out of the composite score preserves the code-enforced separation between observation and execution.
- All thresholds live in `config.yaml`; nothing is hardcoded, consistent with the rest of the system.
