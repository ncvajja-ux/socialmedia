from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class Action(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class Stance(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


# ── Core agent result ──────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    agent_name: str
    score: float                    # -10 to +10
    confidence: float               # 0 to 1
    reasoning: str
    data_snapshot: dict = field(default_factory=dict)


# ── LLM output models ──────────────────────────────────────────────────────────

class ResearchPlan(BaseModel):
    ticker: str
    stance: Stance
    summary: str
    key_bulls: list[str] = Field(default_factory=list)
    key_bears: list[str] = Field(default_factory=list)
    conviction: float = Field(ge=0.0, le=1.0)


class TraderProposal(BaseModel):
    ticker: str
    action: Action
    entry_price: float
    stop_loss: float
    target_price: float
    quantity: int
    position_size_pct: float        # fraction of capital
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)


# ── Broker order ───────────────────────────────────────────────────────────────

@dataclass
class OrderRequest:
    ticker: str
    action: Action
    quantity: int
    entry_price: float
    stop_loss: float
    target_price: float
    variety: str = "VARIETY_REGULAR"
    product: str = "PRODUCT_MIS"
    order_type: str = "ORDER_TYPE_LIMIT"


# ── Debate state TypedDicts ────────────────────────────────────────────────────

class DebateMessage(TypedDict):
    role: str       # "bull" | "bear" | "facilitator"
    content: str


class InvestDebateState(TypedDict):
    ticker: str
    composite_score: float
    agent_results: list[dict]
    messages: list[DebateMessage]
    round: int
    research_plan: ResearchPlan | None


class RiskDebateState(TypedDict):
    ticker: str
    proposal: TraderProposal | None
    risk_flags: list[str]
    approved: bool
