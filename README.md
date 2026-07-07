# Stock Scraper

A fully local, multi-agent stock market analysis system for Indian markets (NSE/BSE). Five specialized agents independently score each stock, a Meta-Evaluator grades their reasoning quality, and a Broker Agent aggregates everything into a trade proposal — all running on your Mac with no cloud APIs.

## Features

- **5 specialist agents** — Technical, Fundamental, News, Volume/Momentum, Portfolio/Risk
- **LLM-as-judge quality gate** — Meta-Evaluator scores each agent's reasoning before the Broker Agent weighs it
- **Bull/Bear debate** — Broker Agent runs a multi-round Ollama debate before deciding
- **Human-in-the-loop UI** — Local FastAPI dashboard with one-click approve/reject/modify
- **52-week-low monitor** — alerts (dashboard + macOS notification) when a watchlist stock makes or nears a 52-week low
- **Code-enforced risk** — VIX gate, position limits, and daily loss cap enforced in Python, not prompts
- **Fully local** — Zerodha Kite Connect for data/execution, Ollama for LLMs, DuckDB for storage
- **Paper mode** — all logic runs without placing real orders until you flip a config flag

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Zerodha Kite Connect                      │
│  KiteTicker WebSocket (live ticks)                          │
│  REST API (historical OHLCV, portfolio, holdings, orders)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
             ┌─────────────▼──────────────┐
             │       kite_client.py        │
             │  Token refresh (6am IST)    │
             │  3-level data fallback:     │
             │  WS cache → REST → error    │
             └─────────────┬──────────────┘
                           │
             ┌─────────────▼──────────────┐
             │       db.py (DuckDB)        │
             │  OHLCV, scores, trades,     │
             │  fundamentals               │
             └─────────────┬──────────────┘
                           │
        ┌──────────────────▼─────────────────────┐
        │           runner.py (asyncio)           │
        │  9:15am / 12:00pm / 3:25pm IST          │
        └──┬──────┬────────┬──────┬──────┬───────┘
           │      │        │      │      │
     ┌─────▼─┐ ┌──▼──┐ ┌──▼──┐ ┌─▼──┐ ┌▼──────────┐
     │Tech   │ │Fund │ │News │ │Vol │ │Portfolio  │
     │Agent  │ │Agent│ │Agent│ │Agent│ │Risk Agent │
     │Pure Py│ │Pure │ │Ollama│ │Pure│ │Pure Py    │
     └───┬───┘ └──┬──┘ └──┬──┘ └─┬──┘ └─────┬─────┘
         └────────┴────────┴──────┴───────────┘
                           │
             ┌─────────────▼──────────────┐
             │       Meta-Evaluator        │
             │  Scores reasoning quality   │
             │  per agent (1–10)           │
             └─────────────┬──────────────┘
                           │
             ┌─────────────▼──────────────┐
             │         Broker Agent        │
             │  Weighted composite score   │
             │  Bull/Bear debate (Ollama)  │
             │  Code-enforced risk check   │
             │  → Kite order placement     │
             └────────────────────────────┘
```

Scores run at **9:15am**, **12:00pm**, and **3:25pm IST** on weekdays via macOS `launchd`.

## Quick Start

### Prerequisites

- Python 3.11+
- [Zerodha Kite Connect](https://kite.trade/) account and API key
- [Ollama](https://ollama.ai/) running locally with `llama3.2:3b` and `llama3.1:8b` pulled
- macOS (for `launchd` scheduling and native notifications)

### Installation

```bash
git clone https://github.com/ncvajja-ux/Stockscraper.git
cd Stockscraper
pip install -r requirements.txt
```

### Configure

Copy and edit the config:

```bash
cp config.yaml.example config.yaml
```

Set your Kite credentials and watchlist at minimum:

```yaml
kite:
  api_key: YOUR_API_KEY
  access_token: YOUR_ACCESS_TOKEN

market:
  watchlist: [RELIANCE, INFY, HDFCBANK, TCS, ICICIBANK]
```

Full configuration reference: [`docs/configuration.md`](docs/configuration.md)

### Run (paper mode)

```bash
# Single run, all tickers in watchlist
python runner.py

# On-demand analysis for one ticker
python runner.py --ticker RELIANCE --mode quick

# Start the web dashboard
uvicorn web.api:app --port 8080
```

Open `http://localhost:8080` to see live scores and approve/reject proposals.

See [`docs/setup.md`](docs/setup.md) for full setup including Kite auth, Ollama models, and launchd scheduling.

## Agents

| Agent | Weight | LLM | Data sources |
|-------|--------|-----|--------------|
| Technical | 25% | None | Kite WebSocket + `kite.historical_data()` |
| Fundamental | 20% | None | Screener.in (yfinance fallback) |
| News & Filing | 15% | Ollama `llama3.2:3b` | NSE announcements + MoneyControl RSS |
| Volume & Momentum | 20% | None | Kite delivery %, OI, NSE FII/DII API |
| Portfolio & Risk | 20% | None | `kite.holdings()`, `kite.positions()`, VIX |

All agents return a score in `[-10, +10]`. If an agent's data is unavailable it returns `None` — its weight drops to 0 and the remaining weights re-normalise automatically.

Full agent specs: [`docs/agents.md`](docs/agents.md)

## Monitors

Alongside the scoring agents, lightweight monitors run on every cycle and raise informational alerts (they never place orders or affect the composite score):

- **52-Week Low** — fires `NEW_52W_LOW` when a watchlist stock trades at or below its trailing 52-week low, or `NEAR_52W_LOW` when it comes within a configurable band (default 1%) above it. Alerts land on the dashboard, in DuckDB, and as a native macOS notification, with a per-ticker cooldown to avoid spam. Also runnable standalone: `python -m monitors.week52_low`.

Full monitor specs: [`docs/monitors.md`](docs/monitors.md)

## Web UI

The FastAPI app at `http://localhost:8080` has five pages:

| Page | URL | Purpose |
|------|-----|---------|
| Watchlist Dashboard | `/` | Live scores per ticker, auto-refreshes every 30s |
| Trade Proposal | `/proposal/<ticker>` | Human-in-the-loop approve / reject / modify |
| Portfolio | `/portfolio` | Holdings, unrealised P&L, sector breakdown |
| Trade History | `/history` | Past trades with post-trade LLM reflection |
| Deep Research | `/research/<ticker>` | On-demand 11+ LLM-call analysis, exportable |

### Proposal screen

```
┌─────────────────────────────────────────────────────┐
│  RELIANCE — BUY  │ Composite: +6.4  │ Conf: 84%     │
├────────────┬────────────────────────────────────────┤
│ Agent      │ Score  │ Quality │ Reasoning excerpt    │
├────────────┼────────────────────────────────────────┤
│ Technical  │ +7.5   │  9/10   │ RSI 32, MACD cross  │
│ Fundamental│ +5.0   │  8/10   │ P/E 18 vs sector 24 │
│ News       │ +4.0   │  7/10   │ Q3 results beat est │
│ Volume     │ +8.0   │  8/10   │ Delivery 68% vs 45% │
│ Portfolio  │ +4.0   │  6/10   │ No existing position│
├────────────┴────────────────────────────────────────┤
│ Bull/Bear Debate Summary                             │
│ Bull: Strong delivery + technical breakout...        │
│ Bear: Broader market weak, VIX at 17...             │
│ Verdict: Overweight                                 │
├─────────────────────────────────────────────────────┤
│ Entry: ₹1,452  │ Stop: ₹1,398  │ Target: ₹1,560    │
│ Qty: 10 shares │ Risk: ₹540 (1.8% of capital)       │
├─────────────────────────────────────────────────────┤
│  [ APPROVE ]     [ REJECT ]     [ MODIFY & APPROVE ]│
└─────────────────────────────────────────────────────┘
```

- **APPROVE** — places Kite order + SL/target GTT immediately
- **REJECT** — logs reason, no order
- **MODIFY** — edit qty/entry/stop/target before placing

In `paper_mode: true` the APPROVE button is disabled and shows "Paper Trade".

## Run Modes

| Mode | LLM calls | Approx. latency | When |
|------|-----------|-----------------|------|
| Quick | 1 (synthesis only) | ~5s | On-demand, single ticker |
| Standard | 6–8 | ~60s | Scheduled 3×/day |
| Deep | 11+ | ~5 min | Manual research |

## Risk Controls

All limits are code-enforced — they cannot be overridden by an LLM:

- **VIX ≥ 20** → no new buy signals pass through
- **Position > 10% of portfolio** → score penalised by −3
- **Sector concentration > 30%** → score penalised by −2
- **Daily loss > 2% of capital** → all new buy signals blocked
- **Anti-pyramid** → already at max position scores −5

## Directory Structure

```
Stock scraper/
├── agents/
│   ├── base_agent.py
│   ├── technical_agent.py
│   ├── fundamental_agent.py
│   ├── news_agent.py
│   ├── volume_agent.py
│   ├── portfolio_agent.py
│   ├── broker_agent.py
│   ├── meta_evaluator.py
│   └── utils/
│       ├── rating.py
│       ├── memory.py
│       ├── reflection.py
│       └── parsing.py
├── analysis/
│   └── indicators.py
├── brokers/
│   ├── base.py
│   └── zerodha.py
├── engine/
│   ├── risk_limits.py
│   └── trade_executor.py
├── market/
│   ├── quotes.py
│   ├── history.py
│   ├── news.py
│   └── fundamentals.py
├── monitors/
│   └── week52_low.py
├── web/
│   ├── api.py
│   └── static/
│       ├── index.html
│       ├── proposal.html
│       ├── portfolio.html
│       ├── history.html
│       ├── research.html
│       └── style.css
├── schemas.py
├── kite_client.py
├── db.py
├── runner.py
└── config.yaml
```

## Tech Stack

| Layer | Library |
|-------|---------|
| Broker / data | `kiteconnect ≥ 4.2.0` |
| Indicators | `stockstats`, `pandas`, `ta` |
| Local LLM | `ollama` (via `httpx`) |
| Database | `duckdb ≥ 0.10` |
| Scraping | `httpx`, `beautifulsoup4` |
| Data models | `pydantic ≥ 2.0` |
| Web | `fastapi`, `uvicorn`, vanilla JS |
| Scheduling | macOS `launchd` |
| Python | `3.11+` |

No LangChain. No LangGraph. No CrewAI. No cloud APIs.

## License

MIT
