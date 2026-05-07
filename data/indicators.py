import pandas as pd
import ta
from models import TechnicalData


def calc_indicators(df: pd.DataFrame) -> TechnicalData:
    """计算技术指标，返回最新值"""
    tech = TechnicalData()
    if df is None or len(df) < 20:
        return tech

    close = df["close"]
    volume = df["volume"]

    tech.price = close.iloc[-1]
    tech.change_pct = df["change_pct"].iloc[-1] if "change_pct" in df.columns else 0.0
    tech.volume = volume.iloc[-1]

    # 均线
    tech.ma5 = close.rolling(5).mean().iloc[-1]
    tech.ma10 = close.rolling(10).mean().iloc[-1]
    tech.ma20 = close.rolling(20).mean().iloc[-1]
    if len(close) >= 60:
        tech.ma60 = close.rolling(60).mean().iloc[-1]

    # RSI
    tech.rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]

    # MACD
    macd = ta.trend.MACD(close)
    tech.macd = macd.macd().iloc[-1]
    tech.macd_signal = macd.macd_signal().iloc[-1]
    tech.macd_hist = macd.macd_diff().iloc[-1]

    # 布林带
    bb = ta.volatility.BollingerBands(close, window=20)
    tech.bb_upper = bb.bollinger_hband().iloc[-1]
    tech.bb_middle = bb.bollinger_mavg().iloc[-1]
    tech.bb_lower = bb.bollinger_lband().iloc[-1]

    # 量比 = 今日成交量 / 过去5日平均
    avg_vol5 = volume.rolling(5).mean().iloc[-2]  # 昨日的5日均量
    tech.volume_ratio = volume.iloc[-1] / avg_vol5 if avg_vol5 > 0 else 1.0

    return tech


def score_technical(tech: TechnicalData) -> tuple[float, list[str]]:
    """技术面打分 (0-100)，返回分数和原因列表"""
    score = 50.0
    reasons = []

    # 均线多头排列
    if tech.price > tech.ma5 > tech.ma10 > tech.ma20:
        score += 15
        reasons.append("均线多头排列")
    elif tech.price < tech.ma5 < tech.ma10 < tech.ma20:
        score -= 10
        reasons.append("均线空头排列")

    # 金叉信号
    if tech.ma5 > tech.ma10:
        score += 5
        reasons.append("5日上穿10日均线")

    # MACD
    if tech.macd_hist > 0:
        score += 8
        reasons.append("MACD红柱")
        if tech.macd > tech.macd_signal:
            score += 5
            reasons.append("MACD金叉")
    else:
        score -= 5
        reasons.append("MACD绿柱")

    # RSI
    if 30 < tech.rsi < 50:
        score += 8
        reasons.append(f"RSI偏低({tech.rsi:.0f})，有反弹空间")
    elif tech.rsi < 30:
        score += 12
        reasons.append(f"RSI超卖({tech.rsi:.0f})")
    elif tech.rsi > 70:
        score -= 10
        reasons.append(f"RSI超买({tech.rsi:.0f})，注意回调")

    # 布林带位置
    if tech.price < tech.bb_lower:
        score += 8
        reasons.append("价格触及布林下轨")
    elif tech.price > tech.bb_upper:
        score -= 5
        reasons.append("价格突破布林上轨")

    # 放量
    if tech.volume_ratio > 1.5:
        score += 5
        reasons.append(f"放量({tech.volume_ratio:.1f}倍)")
    elif tech.volume_ratio < 0.5:
        score -= 3
        reasons.append(f"缩量({tech.volume_ratio:.1f}倍)")

    return max(0, min(100, score)), reasons


def score_fundamental(pe: float, pb: float, roe: float,
                      revenue_growth: float, profit_growth: float,
                      debt_ratio: float) -> tuple[float, list[str]]:
    """基本面打分 (0-100)"""
    score = 50.0
    reasons = []

    # PE
    if 0 < pe < 15:
        score += 10
        reasons.append(f"PE低估({pe:.1f})")
    elif 15 <= pe < 30:
        score += 3
        reasons.append(f"PE合理({pe:.1f})")
    elif pe > 60:
        score -= 8
        reasons.append(f"PE偏高({pe:.1f})")
    elif pe < 0:
        score -= 15
        reasons.append("亏损")

    # PB
    if 0 < pb < 1.5:
        score += 5
        reasons.append(f"PB低估({pb:.2f})")
    elif pb > 5:
        score -= 5
        reasons.append(f"PB偏高({pb:.2f})")

    # ROE
    if roe > 15:
        score += 10
        reasons.append(f"ROE优秀({roe:.1f}%)")
    elif roe > 10:
        score += 5
        reasons.append(f"ROE良好({roe:.1f}%)")
    elif 0 < roe < 5:
        score -= 3
        reasons.append(f"ROE偏低({roe:.1f}%)")

    # 营收增长
    if revenue_growth > 20:
        score += 8
        reasons.append(f"营收高增长({revenue_growth:.1f}%)")
    elif revenue_growth > 10:
        score += 4
        reasons.append(f"营收稳增({revenue_growth:.1f}%)")
    elif revenue_growth < -10:
        score -= 8
        reasons.append(f"营收下滑({revenue_growth:.1f}%)")

    # 利润增长
    if profit_growth > 30:
        score += 8
        reasons.append(f"利润高增长({profit_growth:.1f}%)")
    elif profit_growth > 10:
        score += 4
    elif profit_growth < -20:
        score -= 10
        reasons.append(f"利润大幅下滑({profit_growth:.1f}%)")

    # 资产负债率
    if debt_ratio > 70:
        score -= 8
        reasons.append(f"负债率偏高({debt_ratio:.1f}%)")

    return max(0, min(100, score)), reasons
