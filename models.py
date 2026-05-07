from dataclasses import dataclass, field
from enum import Enum


class Signal(Enum):
    STRONG_BUY = "强烈推荐"
    BUY = "推荐"
    HOLD = "观望"
    AVOID = "回避"


@dataclass
class StockBasic:
    code: str
    name: str
    industry: str = ""
    market_cap: float = 0.0


@dataclass
class TechnicalData:
    price: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    rsi: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    volume_ratio: float = 1.0


@dataclass
class FundamentalData:
    pe: float = 0.0
    pb: float = 0.0
    roe: float = 0.0
    revenue_growth: float = 0.0
    profit_growth: float = 0.0
    gross_margin: float = 0.0
    debt_ratio: float = 0.0


@dataclass
class ScreenerResult:
    stock: StockBasic
    tech: TechnicalData
    fund: FundamentalData
    screener_score: float = 0.0
    screener_reasons: list = field(default_factory=list)


@dataclass
class AnalystResult:
    screener: ScreenerResult
    tech_score: float = 0.0
    fund_score: float = 0.0
    momentum_score: float = 0.0
    total_score: float = 0.0
    signal: Signal = Signal.HOLD
    reasons: list = field(default_factory=list)
    risks: list = field(default_factory=list)
