"""
Agent B - 深度分析师
职责：对 Agent A 筛选出的候选股票做深度分析
综合技术面细节 + 基本面健康度 + 趋势动量，输出最终推荐
"""

from models import ScreenerResult, AnalystResult, Signal
from data.indicators import score_technical, score_fundamental


def run_analyst(
    candidates: list[ScreenerResult],
    progress_callback=None,
) -> list[AnalystResult]:
    """
    Agent B 主流程：
    1. 接收 Agent A 的候选池
    2. 对每只股票做深度多维度分析
    3. 生成最终推荐信号和综合评分
    """
    results = []

    for i, cand in enumerate(candidates):
        if progress_callback and i % 3 == 0:
            progress_callback(f"Agent B: 深度分析中... ({i+1}/{len(candidates)})")

        try:
            result = _deep_analyze(cand)
            results.append(result)
        except Exception as e:
            print(f"[Analyst] 分析失败 {cand.stock.code}: {e}")

    # 按总分排序
    results.sort(key=lambda r: r.total_score, reverse=True)

    if progress_callback:
        progress_callback(f"Agent B: 分析完成，共 {len(results)} 只股票")

    return results


def _deep_analyze(cand: ScreenerResult) -> AnalystResult:
    """深度分析单只股票"""
    tech = cand.tech
    fund = cand.fund

    # 1. 技术面深度评分
    tech_score, tech_details = _tech_deep_score(tech)

    # 2. 基本面健康度评分
    fund_score, fund_details = _fund_health_score(fund)

    # 3. 趋势动量评分
    momentum_score, momentum_details = _momentum_score(tech, cand.screener_score)

    # 4. 综合打分 (技术35% + 基本面35% + 动量30%)
    total = tech_score * 0.35 + fund_score * 0.35 + momentum_score * 0.30

    # 5. 生成信号
    signal = _classify_signal(total, tech, fund)

    # 6. 汇总理由和风险
    reasons = tech_details + fund_details + momentum_details
    risks = _identify_risks(tech, fund)

    return AnalystResult(
        screener=cand,
        tech_score=round(tech_score, 1),
        fund_score=round(fund_score, 1),
        momentum_score=round(momentum_score, 1),
        total_score=round(total, 1),
        signal=signal,
        reasons=reasons,
        risks=risks,
    )


def _tech_deep_score(tech) -> tuple[float, list[str]]:
    """技术面深度评分"""
    score, reasons = score_technical(tech)

    # 额外深度指标
    # 均线发散度
    if tech.ma5 > 0 and tech.ma20 > 0:
        spread = (tech.ma5 - tech.ma20) / tech.ma20 * 100
        if 2 < spread < 10:
            score += 5
            reasons.append(f"均线健康发散({spread:.1f}%)")
        elif spread > 15:
            score -= 5
            reasons.append(f"均线过度发散({spread:.1f}%)，短期回调风险")

    # 价格相对布林带位置
    if tech.bb_upper > tech.bb_lower > 0:
        bb_pos = (tech.price - tech.bb_lower) / (tech.bb_upper - tech.bb_lower)
        if bb_pos < 0.2:
            score += 5
            reasons.append("价格接近布林下轨")
        elif bb_pos > 0.9:
            score -= 3
            reasons.append("价格接近布林上轨")

    return max(0, min(100, score)), reasons


def _fund_health_score(fund) -> tuple[float, list[str]]:
    """基本面健康度评分"""
    score, reasons = score_fundamental(
        fund.pe, fund.pb, fund.roe,
        fund.revenue_growth, fund.profit_growth, fund.debt_ratio,
    )

    # 增长质量
    if fund.revenue_growth > 0 and fund.profit_growth > fund.revenue_growth:
        score += 5
        reasons.append("利润增速快于营收，盈利能力提升")

    if fund.revenue_growth > 0 and fund.profit_growth < 0:
        score -= 5
        reasons.append("增收不增利")

    return max(0, min(100, score)), reasons


def _momentum_score(tech, screener_score: float) -> tuple[float, list[str]]:
    """趋势动量评分"""
    score = screener_score  # 以筛选分作为基础
    reasons = []

    # 量价配合
    if tech.change_pct > 0 and tech.volume_ratio > 1.2:
        score += 8
        reasons.append("量价齐升")
    elif tech.change_pct < 0 and tech.volume_ratio > 1.5:
        score -= 5
        reasons.append("放量下跌")
    elif tech.change_pct > 0 and tech.volume_ratio < 0.7:
        score += 3
        reasons.append("缩量上涨，抛压轻")

    # RSI动量
    if 40 < tech.rsi < 60:
        score += 3
        reasons.append("RSI中性区，方向待选择")
    elif tech.rsi > 65:
        score += 5
        reasons.append("RSI偏强，多头动量")

    return max(0, min(100, score)), reasons


def _classify_signal(total: float, tech, fund) -> Signal:
    """根据综合评分和技术形态给出信号"""
    if total >= 75 and tech.rsi < 70:
        return Signal.STRONG_BUY
    elif total >= 60:
        return Signal.BUY
    elif total >= 40:
        return Signal.HOLD
    else:
        return Signal.AVOID


def _identify_risks(tech, fund) -> list[str]:
    """识别风险点"""
    risks = []

    if tech.rsi > 75:
        risks.append("RSI严重超买，短期回调概率大")
    if tech.volume_ratio > 3:
        risks.append("异常放量，注意主力出货可能")
    if tech.change_pct > 9:
        risks.append("涨停板，追高风险")
    if tech.price > tech.bb_upper * 1.02:
        risks.append("突破布林上轨，回调风险增加")
    if fund.debt_ratio > 80:
        risks.append(f"资产负债率过高({fund.debt_ratio:.0f}%)")
    if fund.pe > 80:
        risks.append(f"估值过高(PE={fund.pe:.0f})")
    if fund.revenue_growth < -20:
        risks.append("营收大幅下滑")

    if not risks:
        risks.append("暂无明显风险信号")

    return risks
