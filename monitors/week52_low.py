"""52-week-low monitor.

Watches every ticker in the configured watchlist and raises an alert when the
live price prints a new 52-week low, or trades within a configurable proximity
band above the existing one.

Pure Python — no LLM. Runs as part of every scheduled `runner.py` cycle and
can also be invoked standalone:

    python -m monitors.week52_low                 # full watchlist
    python -m monitors.week52_low --ticker INFY   # single ticker

The 52-week low is computed from the local DuckDB `ohlcv` table; if the table
has insufficient history for a ticker, the monitor falls back to
`kite.historical_data()` (1-year daily candles). Live prices use the standard
kite_client fallback chain: WebSocket cache → REST quote → error.

Alerts are persisted to the `week52_low_alerts` DuckDB table, surfaced on the
web dashboard, and (optionally) sent as a native macOS notification. A
per-ticker cooldown suppresses repeat alerts while a stock keeps grinding
along its low.

All thresholds come from `config.yaml` under `monitors.week52_low` — nothing
is hardcoded here.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from config import load_config
from db import Database
from kite_client import KiteClient
from schemas import AlertKind, Week52LowAlert

logger = logging.getLogger(__name__)


class Week52LowMonitor:
    """Alerts when a watchlist ticker makes or nears a 52-week low."""

    def __init__(self, kite: KiteClient, db: Database, cfg=None):
        self.kite = kite
        self.db = db
        cfg = cfg or load_config()
        mon = cfg.monitors.week52_low
        self.enabled: bool = mon.enabled
        self.proximity_pct: float = mon.proximity_pct
        self.cooldown: timedelta = timedelta(hours=mon.cooldown_hours)
        self.lookback_days: int = mon.lookback_days
        self.notify_enabled: bool = mon.notify
        self.dashboard_url: str = cfg.web.base_url

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, tickers: list[str]) -> list[Week52LowAlert]:
        """Check every ticker and return the alerts that fired this cycle."""
        if not self.enabled:
            return []
        alerts: list[Week52LowAlert] = []
        for ticker in tickers:
            try:
                alert = await self.check(ticker)
            except Exception:
                # A single bad ticker must not sink the rest of the sweep.
                logger.exception("52w-low check failed for %s", ticker)
                continue
            if alert is not None:
                alerts.append(alert)
        return alerts

    async def check(self, ticker: str) -> Week52LowAlert | None:
        """Return an alert for `ticker`, or None if no condition is met.

        Cooldown, data-unavailable, and price-above-band all return None.
        """
        if self._in_cooldown(ticker):
            return None

        week52_low = await self._week52_low(ticker)
        last_price = await self.kite.last_price(ticker)
        if week52_low is None or last_price is None:
            logger.warning("52w-low monitor: no data for %s, skipping", ticker)
            return None

        distance_pct = (last_price - week52_low) / week52_low
        if last_price <= week52_low:
            kind = AlertKind.NEW_52W_LOW
        elif distance_pct <= self.proximity_pct:
            kind = AlertKind.NEAR_52W_LOW
        else:
            return None

        alert = Week52LowAlert(
            ticker=ticker,
            kind=kind,
            last_price=last_price,
            week52_low=week52_low,
            distance_pct=distance_pct,
            triggered_at=datetime.now(),
        )
        self._persist(alert)
        if self.notify_enabled:
            self._notify(alert)
        logger.info(
            "%s: %s at %.2f (52w low %.2f, %+.2f%%)",
            ticker, kind.value, last_price, week52_low, distance_pct * 100,
        )
        return alert

    # ── 52-week low ───────────────────────────────────────────────────────────

    async def _week52_low(self, ticker: str) -> float | None:
        """Trailing 52-week low: local OHLCV first, Kite REST as fallback."""
        row = self.db.conn.execute(
            """
            SELECT MIN(low), COUNT(*)
            FROM ohlcv
            WHERE ticker = ?
              AND date >= CURRENT_DATE - INTERVAL (?) DAY
            """,
            [ticker, self.lookback_days],
        ).fetchone()
        low, n_days = (row or (None, 0))
        # Require a reasonably complete year of local candles (~250 trading
        # days per year on NSE); otherwise the "low" is just a recent dip.
        if low is not None and n_days >= 200:
            return float(low)

        candles = await self.kite.historical_data(ticker, days=self.lookback_days)
        if not candles:
            return None
        return min(c["low"] for c in candles)

    # ── Persistence / cooldown ────────────────────────────────────────────────

    def _in_cooldown(self, ticker: str) -> bool:
        row = self.db.conn.execute(
            "SELECT MAX(triggered_at) FROM week52_low_alerts WHERE ticker = ?",
            [ticker],
        ).fetchone()
        last = row[0] if row else None
        return last is not None and datetime.now() - last < self.cooldown

    def _persist(self, alert: Week52LowAlert) -> None:
        self.db.conn.execute(
            """
            INSERT INTO week52_low_alerts
                (ticker, triggered_at, kind, last_price, week52_low, distance_pct)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                alert.ticker,
                alert.triggered_at,
                alert.kind.value,
                alert.last_price,
                alert.week52_low,
                alert.distance_pct,
            ],
        )

    def _notify(self, alert: Week52LowAlert) -> None:
        from web.notifications import notify  # osascript under the hood

        label = "NEW 52-week LOW" if alert.kind is AlertKind.NEW_52W_LOW else "near 52-week low"
        notify(
            f"{alert.ticker} {label}: ₹{alert.last_price:,.2f}",
            f"{self.dashboard_url}/?highlight={alert.ticker}",
        )


# ── Standalone entry point ─────────────────────────────────────────────────────

async def _main() -> None:
    parser = argparse.ArgumentParser(description="Run the 52-week-low monitor once.")
    parser.add_argument("--ticker", help="Check a single ticker instead of the watchlist")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    monitor = Week52LowMonitor(KiteClient(), Database(), cfg)
    tickers = [args.ticker] if args.ticker else cfg.market.watchlist
    alerts = await monitor.run(tickers)
    if not alerts:
        print("No 52-week-low alerts.")
    for a in alerts:
        print(
            f"{a.ticker}: {a.kind.value} — last ₹{a.last_price:,.2f} "
            f"vs 52w low ₹{a.week52_low:,.2f} ({a.distance_pct:+.2%})"
        )


if __name__ == "__main__":
    asyncio.run(_main())
