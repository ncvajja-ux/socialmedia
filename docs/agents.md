# Agent Reference

All agents implement a common interface:

```python
class BaseAgent:
    async def score(self, ticker: str) -> AgentResult | None
```

`AgentResult` fields:

| Field | Type | Description |
|-------|------|-------------|
| `score` | `float` | −10 (strongly bearish) to +10 (strongly bullish) |
| `confidence` | `float` | 0–1 |
| `reasoning` | `str` | Plain-English explanation used by the Meta-Evaluator |
| `data_snapshot` | `dict` | Raw inputs that produced the score |

If an agent's data is unavailable it returns `None`. Its weight drops to 0 and the remaining weights re-normalise automatically.

---

## Technical Agent

**File:** `agents/technical_agent.py`  
**Weight:** 25%  
**LLM:** None — pure Python  
**Data:** KiteTicker live price + `kite.historical_data()` (1-year OHLCV)  
**Library:** `stockstats`

### Signals

| Signal | Bullish condition | Bearish condition | Max points |
|--------|------------------|------------------|------------|
| RSI (14) | < 35 (oversold) | > 65 (overbought) | ±3 |
| MACD crossover | MACD line > signal line | MACD line < signal line | ±2.5 |
| Price vs EMA20/EMA50 | Above both EMAs | Below both EMAs | ±2 |
| Price vs SMA200 | Above SMA200 | Below SMA200 | ±1.5 |
| Bollinger Band position | Near lower band | Near upper band | ±0.5 |
| Volume vs 20-day avg | > 1.5× average (confirmation) | < 0.5× average (divergence) | ±0.5 |

Raw sum clamped to [−10, +10].

---

## Fundamental Agent

**File:** `agents/fundamental_agent.py`  
**Weight:** 20%  
**LLM:** None — pure Python rule engine  
**Data:** Screener.in (scraped), yfinance as fallback for Indian stocks

### Scoring rules (starts at 0)

| Metric | Condition | Score |
|--------|-----------|-------|
| P/E vs sector median | < 0.8× sector median | +2.5 |
| P/E vs sector median | > 1.5× sector median | −2.5 |
| ROE | ≥ 15% | +2 |
| ROE | < 8% | −2 |
| Promoter holding | ≥ 50% | +1.5 |
| Promoter pledge | > 25% | −2.5 |
| Debt-to-Equity | < 0.5 | +1 |
| Debt-to-Equity | > 1.5 | −1.5 |
| Revenue growth YoY | > 15% | +1 |
| Revenue growth YoY | < 0% | −1 |

Score clamped to [−10, +10].

---

## News & Filing Agent

**File:** `agents/news_agent.py`  
**Weight:** 15%  
**LLM:** Ollama (`llama3.2:3b`)  
**Data:** NSE announcement API + MoneyControl RSS (last 48 hours)

### Pipeline

1. Fetch announcements and headlines for the ticker from the last 48 hours
2. For each item, Ollama classifies: `BULLISH` / `BEARISH` / `NEUTRAL` + brief reason
3. Apply recency weighting:
   - Last 6 hours: weight 1.0
   - 6–24 hours: weight 0.6
   - 24–48 hours: weight 0.3
4. Weighted average mapped to [−10, +10]

### LLM output format

All agent prompts enforce a structured delimiter format for reliable local-model parsing:

```
[BEGIN CHAIN OF THOUGHT REASONING]
...reasoning...
[END CHAIN OF THOUGHT REASONING]
[BEGIN SCORE] I assign a score of X out of 10 [END SCORE]
```

`preprocess_response()` in `agents/utils/parsing.py` normalises whitespace and extracts the score via regex. On parse failure: 2 retries, then fallback score 0.

---

## Volume & Momentum Agent

**File:** `agents/volume_agent.py`  
**Weight:** 20%  
**LLM:** None — pure Python  
**Data:** `kite.historical_data()` (delivery %, OI) + NSE FII/DII API

### Signals

| Signal | Bullish condition | Bearish condition | Max points |
|--------|------------------|------------------|------------|
| Delivery % vs 30-day avg | > 1.3× average | < 0.7× average | ±3 |
| OI change (F&O) | Rising OI + price rising | Rising OI + price falling | ±3 |
| FII net flow (5-day streak) | Consecutive buying > ₹500Cr/day | Consecutive selling > ₹500Cr/day | ±2.5 |
| DII flow (confirmation) | Same direction as FII | Opposing FII direction | ±1.5 |

Score clamped to [−10, +10].

---

## Portfolio & Risk Agent

**File:** `agents/portfolio_agent.py`  
**Weight:** 20%  
**LLM:** None — pure Python  
**Data:** `kite.holdings()`, `kite.positions()`, live VIX quote

### Hard gates (code-enforced — cannot be bypassed by LLM output)

| Condition | Effect |
|-----------|--------|
| VIX ≥ 20 | Score capped at 0 — no buy signals pass through |
| Existing position > 10% of portfolio | Score penalised by −3 |
| Sector concentration > 30% | Score penalised by −2 |
| Daily loss already > 2% of capital | Score capped at 0 |

### Scoring rules

| Condition | Score |
|-----------|-------|
| No existing position (room to add) | +2 |
| Existing position, unrealised profit > 5% | +1 |
| Existing position, unrealised loss > 5% | −2 |
| Anti-pyramid: already at maximum position size | −5 |
| Portfolio cash < 10% | −1 |

---

## Meta-Evaluator

**File:** `agents/meta_evaluator.py`  
**LLM:** Ollama (`llama3.2:3b`)

After all five agents run, a single Ollama call grades each agent's `reasoning` string on three criteria (1–10 each):

| Criterion | What it measures |
|-----------|-----------------|
| `signal_clarity` | Is the reasoning specific and grounded in data, or vague and generic? |
| `data_recency` | Is the agent using fresh data or stale / assumed values? |
| `risk_acknowledgment` | Does the reasoning acknowledge uncertainty and downside scenarios? |

**Quality score** = mean of the three criteria (1–10).

### Weight multipliers

| Quality score | Multiplier | Effect |
|---------------|------------|--------|
| 8–10 | 1.00 | Full weight |
| 5–7 | 0.75 | Reduced weight |
| 1–4 | 0.40 | Heavily penalised but not dropped |

The Broker Agent receives `effective_weight = base_weight × quality_multiplier` per agent. Effective weights are re-normalised to sum to 1 before the composite score is computed.

---

## Broker Agent

**File:** `agents/broker_agent.py`  
**LLM:** Ollama (`llama3.1:8b` or `mistral:7b`)  
**Inputs:** 5 `AgentResult` objects + quality multipliers from the Meta-Evaluator

### Step 1 — Weighted composite score

```
composite = Σ(agent.score × effective_weight) / Σ(effective_weights)
```

### Step 2 — Bull/Bear debate

Five-round structured debate (rounds configurable in `config.yaml`):

| Round | Speaker | Content |
|-------|---------|---------|
| 1 | Bull | Opening case from agent evidence |
| 2 | Bear | Counter-argument |
| 3 | Bull | Rebuttal |
| 4 | Bear | Rebuttal |
| 5 | Facilitator | Synthesis → `ResearchPlan` (Buy / Overweight / Hold / Underweight / Sell) |

### Step 3 — TraderProposal

Single Ollama call produces:

| Field | Source |
|-------|--------|
| `action` | BUY / HOLD / SELL |
| `entry_price` | LLM |
| `stop_loss` | ATR-based, computed in Python |
| `position_sizing` | `qty = (capital × risk_pct) / ATR` — computed in Python, not by LLM |
| `reasoning` | Plain-English rationale |

### Step 4 — Risk gate (code-enforced)

Before any order is placed:

1. Check `RiskLimits`: daily loss cap, trade count, per-symbol limit, anti-pyramid rule
2. Re-confirm VIX level
3. Confirm portfolio cash available
4. Show order preview → user approves via web UI (auto-confirm available in paper mode)

### Step 5 — Kite order placement

`kite.place_order()` with `VARIETY_REGULAR`. Automatically creates stop-loss and target GTT orders.

### Thresholds

| Parameter | Default | Config key |
|-----------|---------|-----------|
| Composite score to trigger BUY | +4.0 | `broker_agent.composite_buy_threshold` |
| Composite score to trigger SELL | −4.0 | `broker_agent.composite_sell_threshold` |
| Confidence for auto-confirm | 0.80 | `broker_agent.confidence_threshold_for_auto_order` |
| Max debate rounds | 5 | `broker_agent.max_debate_rounds` |

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Kite WebSocket drops | App-level reconnect with exponential backoff (2s, 4s, 8s, 16s) |
| Kite token expired mid-session | `KiteException` caught, re-auth flow triggered |
| Agent data unavailable | Agent returns `None`, weight → 0, others re-normalise |
| Ollama call fails | 2 retries → fallback score 0 (neutral), logged |
| Ollama parse fails | `preprocess_response()` normalisation → regex retry → fallback 0 |
| All 5 agents abstain | Broker Agent returns HOLD, no order placed |
| Risk limit breach | `RiskLimitError` raised, order blocked, event logged to DuckDB |
| Mid-debate LLM failure | Degrades to composite scorecard only with HOLD default |
| Screener.in scrape fails | Falls back to yfinance for Indian stock fundamentals |
