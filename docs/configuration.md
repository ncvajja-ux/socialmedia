# Configuration Reference

All settings live in `config.yaml` at the project root. No magic numbers are hardcoded in the source — every threshold references this file.

## Full annotated config

```yaml
# ─── Market ───────────────────────────────────────────────────────────────────
market:
  exchange: NSE                           # NSE or BSE
  watchlist:                              # Tickers to analyse on each scheduled run
    - RELIANCE
    - INFY
    - HDFCBANK
    - TCS
    - ICICIBANK
  run_times_ist:                          # When runner.py fires (launchd uses these)
    - "09:15"
    - "12:00"
    - "15:25"
  timezone: Asia/Kolkata

# ─── Kite Connect ─────────────────────────────────────────────────────────────
kite:
  api_key: YOUR_API_KEY
  api_secret: YOUR_API_SECRET
  access_token: YOUR_ACCESS_TOKEN         # Populated by scripts/kite_auth.py
  token_reset_time_ist: "06:00"          # Zerodha tokens expire at 6am IST daily
  ws_reconnect_backoff_seconds:           # Exponential backoff for WebSocket reconnects
    - 2
    - 4
    - 8
    - 16

# ─── Agents ───────────────────────────────────────────────────────────────────
agents:
  weights:
    technical: 0.25                       # Must sum to 1.0 across all five agents
    fundamental: 0.20
    news: 0.15
    volume: 0.20
    portfolio_risk: 0.20
  score_range: [-10, 10]                  # All agents clamp output to this range

# ─── Signal Thresholds ────────────────────────────────────────────────────────
thresholds:
  # Technical (standard TA convention)
  rsi_oversold: 35
  rsi_overbought: 65

  # Volume (NSE delivery data norms)
  delivery_pct_bullish_multiplier: 1.3   # Delivery % > 1.3× 30-day avg = bullish
  delivery_pct_bearish_multiplier: 0.7   # Delivery % < 0.7× 30-day avg = bearish

  # FII/DII (NSE FII report thresholds used by analysts)
  fii_streak_threshold_cr: 500           # ₹500 Cr/day net flow counts as a streak

  # Risk (standard 2% rule + SEBI position-size guidelines)
  vix_no_buy_threshold: 20               # VIX ≥ 20 blocks all new buy signals
  max_position_pct: 0.10                 # Single ticker cap as fraction of portfolio
  max_sector_pct: 0.30                   # Sector concentration cap
  daily_loss_cap_pct: 0.02               # Block new buys if day P&L < −2% of capital
  per_trade_risk_pct: 0.02               # Risk per trade (used in position sizing)

  # PCR (NSE options data convention)
  pcr_bearish: 1.2                       # Put-Call Ratio above this = bearish
  pcr_bullish: 0.8                       # Put-Call Ratio below this = bullish

# ─── Monitors ─────────────────────────────────────────────────────────────────
monitors:
  week52_low:
    enabled: true
    proximity_pct: 0.01                  # Alert when price is within 1% above the 52-week low
    cooldown_hours: 24                   # Suppress repeat alerts per ticker for this long
    lookback_days: 365                   # Trailing window used to compute the low
    notify: true                         # Send a native macOS notification on alert

# ─── Broker Agent ─────────────────────────────────────────────────────────────
broker_agent:
  composite_buy_threshold: 4.0           # Composite score must exceed this to trigger BUY
  composite_sell_threshold: -4.0         # Composite score must fall below this for SELL
  max_debate_rounds: 5                   # Bull/Bear debate rounds (1 round = 1 LLM call)
  confidence_threshold_for_auto_order: 0.80  # Auto-confirm orders above this confidence
  paper_mode: true                       # Set false only when ready for live trading

# ─── Ollama ───────────────────────────────────────────────────────────────────
ollama:
  base_url: http://localhost:11434
  fast_model: llama3.2:3b                # Used by: News agent, Meta-Evaluator
  deep_model: llama3.1:8b                # Used by: Broker Agent debate + synthesis

# ─── Meta-Evaluator ───────────────────────────────────────────────────────────
meta_evaluator:
  quality_multipliers:
    high: 1.00                           # Quality score 8–10 → full agent weight
    mid: 0.75                            # Quality score 5–7 → 75% of agent weight
    low: 0.40                            # Quality score 1–4 → 40% of agent weight

# ─── Storage ──────────────────────────────────────────────────────────────────
storage:
  duckdb_path: ./data/stockscraper.duckdb
  memory_log_path: ./data/trade_memory.md
  results_dir: ./data/results/
```

---

## Key settings explained

### `broker_agent.paper_mode`

When `true`:
- All analysis and debate runs normally
- The APPROVE button in the web UI is disabled (shows "Paper Trade" label)
- No orders are sent to Kite Connect
- Proposals are logged to DuckDB as if they were real trades for review

Set to `false` only after you have verified the system is working correctly over multiple days in paper mode.

### `thresholds.vix_no_buy_threshold`

When India VIX is at or above this value, the Portfolio & Risk Agent caps its output score at 0 regardless of other signals. This is a hard gate in Python — it cannot be overridden by LLM reasoning.

The default of 20 reflects the threshold at which elevated market volatility makes new long positions inadvisable. Adjust based on your own risk tolerance.

### `agents.weights`

Weights must sum to exactly 1.0. If you change them, verify with:

```python
from config import load_config
cfg = load_config()
assert abs(sum(cfg.agents.weights.values()) - 1.0) < 1e-9
```

### `broker_agent.composite_buy_threshold`

The Broker Agent only progresses to the Bull/Bear debate and order placement if the raw composite score exceeds this threshold. Raising it (e.g. to 5.0 or 6.0) reduces signal frequency and requires stronger consensus across agents.

### `monitors.week52_low`

Runs on every scheduled cycle (and standalone via `python -m monitors.week52_low`). For each watchlist ticker it compares the live price against the trailing 52-week low computed from local OHLCV:

- **Price ≤ 52-week low** → `NEW_52W_LOW` alert
- **Price within `proximity_pct` above the low** → `NEAR_52W_LOW` alert

`cooldown_hours` prevents alert spam when a stock keeps trading along its low — once a ticker alerts, it stays quiet for that many hours regardless of further prints. Alerts are informational only: they are logged to DuckDB and shown on the dashboard, but do not feed the composite score or place orders.

### `ollama.fast_model` / `ollama.deep_model`

Any model available in your local Ollama installation can be used. The delimiter-based output format (`[BEGIN SCORE]...[END SCORE]`) is designed to work reliably with smaller local models.

Recommended substitutions:

| Default | Alternative | Notes |
|---------|-------------|-------|
| `llama3.2:3b` | `mistral:7b` | More accurate, ~2× slower |
| `llama3.1:8b` | `llama3.1:70b` | Much more accurate, requires ~48GB VRAM |

---

## DuckDB storage schema

### `scores` table
```sql
ticker        TEXT,
timestamp     TIMESTAMP,
agent         TEXT,
score         FLOAT,
confidence    FLOAT,
quality_score FLOAT,
reasoning     TEXT
```

### `trades` table
```sql
ticker          TEXT,
timestamp       TIMESTAMP,
action          TEXT,
entry_price     FLOAT,
stop_loss       FLOAT,
quantity        INT,
composite_score FLOAT,
order_id        TEXT,
status          TEXT
```

### `ohlcv` table
```sql
ticker        TEXT,
date          DATE,
open          FLOAT,
high          FLOAT,
low           FLOAT,
close         FLOAT,
volume        BIGINT,
delivery_pct  FLOAT
```

### `week52_low_alerts` table
```sql
ticker        TEXT,
triggered_at  TIMESTAMP,
kind          TEXT,          -- NEW_52W_LOW | NEAR_52W_LOW
last_price    FLOAT,
week52_low    FLOAT,
distance_pct  FLOAT          -- (last_price - week52_low) / week52_low
```

### `fundamentals` table
```sql
ticker           TEXT,
fetched_date     DATE,
pe_ratio         FLOAT,
roe              FLOAT,
promoter_holding FLOAT,
pledge_pct       FLOAT,
debt_equity      FLOAT,
revenue_growth   FLOAT,
source           TEXT
```
