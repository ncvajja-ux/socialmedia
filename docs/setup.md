# Setup Guide

Step-by-step instructions for getting Stock Scraper running on macOS.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Use `pyenv` or system Python |
| Zerodha account | — | Kite Connect API subscription required |
| Ollama | latest | Must be running before you start the app |
| macOS | Any recent | `launchd` used for scheduling; notifications use native macOS API |

---

## 1. Install Dependencies

```bash
git clone https://github.com/ncvajja-ux/Stockscraper.git
cd Stockscraper
pip install -r requirements.txt
```

Core packages installed:

```
kiteconnect>=4.2.0
duckdb>=0.10
pydantic>=2.0
httpx
beautifulsoup4
stockstats
pandas
ta
fastapi
uvicorn
pyyaml
```

---

## 2. Zerodha Kite Connect Setup

### 2.1 Create a Kite Connect app

1. Log in to [kite.trade/developers](https://kite.trade/developers)
2. Create a new app — set the redirect URL to `http://127.0.0.1:5000/callback`
3. Note your **API key** and **API secret**

### 2.2 First-time authentication

Zerodha uses a two-step OAuth flow. Run the auth helper once:

```bash
python scripts/kite_auth.py --api-key YOUR_KEY --api-secret YOUR_SECRET
```

This opens a browser, asks you to log in to Zerodha, and saves the `access_token` to `config.yaml`.

### 2.3 Daily token refresh

Zerodha access tokens expire at **6:00am IST** every day. The app handles this automatically via `kite_client.py` — it re-authenticates before the 9:15am run. No manual action needed after initial setup.

---

## 3. Ollama Setup

### 3.1 Install Ollama

```bash
# macOS
brew install ollama
```

Or download from [ollama.ai](https://ollama.ai).

### 3.2 Pull required models

```bash
ollama pull llama3.2:3b    # News agent + Meta-Evaluator (fast)
ollama pull llama3.1:8b    # Broker Agent debate + synthesis (deep)
```

### 3.3 Start Ollama

```bash
ollama serve
```

Ollama must be running at `http://localhost:11434` before you start the app. Add it to your login items to have it start automatically.

---

## 4. Configuration

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` — minimum required fields:

```yaml
kite:
  api_key: YOUR_API_KEY
  access_token: YOUR_ACCESS_TOKEN   # populated by kite_auth.py

market:
  watchlist: [RELIANCE, INFY, HDFCBANK, TCS, ICICIBANK]
```

Leave `broker_agent.paper_mode: true` until you're confident the system is working correctly.

Full reference: [`docs/configuration.md`](configuration.md)

---

## 5. Initialise the Database

```bash
python -c "from db import Database; Database().initialise()"
```

Creates `data/stockscraper.duckdb` with all tables.

---

## 6. Run Manually

```bash
# Standard run across all watchlist tickers
python runner.py

# Quick single-ticker run (~5s)
python runner.py --ticker RELIANCE --mode quick

# Deep research run (~5 min, full LLM analysis)
python runner.py --ticker RELIANCE --mode deep
```

---

## 7. Start the Web Dashboard

```bash
uvicorn web.api:app --host 127.0.0.1 --port 8080 --reload
```

Open `http://localhost:8080` in your browser.

---

## 8. Schedule with launchd (Automatic Daily Runs)

Create `~/Library/LaunchAgents/com.stockscraper.runner.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.stockscraper.runner</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/python3</string>
    <string>/path/to/Stockscraper/runner.py</string>
  </array>

  <key>StartCalendarInterval</key>
  <array>
    <!-- 9:15am IST = 3:45am UTC -->
    <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>45</integer></dict>
    <!-- 12:00pm IST = 6:30am UTC -->
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>30</integer></dict>
    <!-- 3:25pm IST = 9:55am UTC -->
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>55</integer></dict>
  </array>

  <key>StandardOutPath</key>
  <string>/path/to/Stockscraper/logs/runner.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/Stockscraper/logs/runner.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.stockscraper.runner.plist
```

To unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.stockscraper.runner.plist
```

---

## 9. macOS Notifications

Trade proposals trigger a native macOS notification linking directly to the proposal approval screen. No extra setup required — the app uses `osascript` internally.

To test:

```bash
python -c "from web.notifications import notify; notify('RELIANCE', 'http://localhost:8080/proposal/RELIANCE')"
```

---

## 10. Going Live (Disabling Paper Mode)

When you're ready to place real orders:

1. Verify the system has been running correctly in paper mode for at least one full week
2. Set `broker_agent.paper_mode: false` in `config.yaml`
3. Review `engine/risk_limits.py` and confirm all hard limits match your risk tolerance
4. Restart the runner and web server

> **Warning:** Live trading will place real orders through Kite Connect. Ensure your risk limits are correct before enabling.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `KiteException: Invalid token` | Run `python scripts/kite_auth.py` again to refresh the token |
| `ConnectionRefusedError` on Ollama | Run `ollama serve` and verify it's listening on port 11434 |
| Agents return `None` consistently | Check that Kite WebSocket is connected — run `python -c "from kite_client import KiteClient; KiteClient().connect()"` |
| Dashboard shows stale scores | Confirm the runner completed without errors: check `logs/runner.log` |
| DuckDB locked error | Another process has the database open — close the other session first |
