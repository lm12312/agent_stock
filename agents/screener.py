"""
Agent A - 全市场筛选器
策略：随机采样 + 并行K线获取 + 技术面快筛 + 基本面精选
"""

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from data.fetcher import get_stock_list, get_kline, get_financial, get_stock_info
from data.indicators import calc_indicators, score_technical, score_fundamental
from models import ScreenerResult, FundamentalData

KLINE_WORKERS = 4  # 并行获取K线的线程数（过多会导致py_mini_racer V8引擎崩溃）


def _fetch_kline_score(stock):
    """获取K线并计算技术评分（线程安全）"""
    try:
        kline = get_kline(stock.code, days=120)
        if kline.empty or len(kline) < 20:
            return None
        tech = calc_indicators(kline)
        tech_score, tech_reasons = score_technical(tech)
        if tech_score < 30:
            return None
        return (stock, tech, tech_score, tech_reasons)
    except Exception:
        return None


def run_screener(
    top_n: int = 15,
    min_market_cap: float = 50.0,
    max_pe: float = 100.0,
    sample_size: int = 100,
    progress_callback=None,
) -> list[ScreenerResult]:
    # Step 1: 获取股票列表（已含市值数据）
    if progress_callback:
        progress_callback("Agent A: 正在获取A股全市场数据...")
    stocks = get_stock_list()
    if not stocks:
        if progress_callback:
            progress_callback("Agent A: 获取股票列表失败")
        return []

    # 按市值预过滤（数据已含市值）
    if min_market_cap > 0:
        stocks = [s for s in stocks if s.market_cap >= min_market_cap]
        if progress_callback:
            progress_callback(f"Agent A: 市值过滤后剩余 {len(stocks)} 只")

    # Step 2: 随机采样
    sample = random.sample(stocks, min(sample_size, len(stocks)))
    if progress_callback:
        progress_callback(f"Agent A: 从 {len(stocks)} 只中采样 {len(sample)} 只，并行获取K线数据...")

    # Step 3: 并行获取K线 + 技术面评分
    tech_results = []
    done_count = 0

    with ThreadPoolExecutor(max_workers=KLINE_WORKERS) as pool:
        futures = {pool.submit(_fetch_kline_score, s): s for s in sample}
        for future in as_completed(futures):
            done_count += 1
            if progress_callback and done_count % 10 == 0:
                progress_callback(f"Agent A: K线分析中... ({done_count}/{len(sample)})")
            result = future.result()
            if result:
                tech_results.append(result)

    # 按技术分排序，取 Top N*3 做基本面分析
    tech_results.sort(key=lambda x: x[2], reverse=True)
    candidates = tech_results[:top_n * 3]

    if progress_callback:
        progress_callback(f"Agent A: 技术面筛选完成，{len(candidates)} 只进入基本面分析...")

    # Step 4: 基本面分析（少量股票，串行即可）
    results = []
    for i, (stock, tech, tech_score, tech_reasons) in enumerate(candidates):
        if progress_callback and i % 5 == 0:
            progress_callback(f"Agent A: 基本面分析中... ({i}/{len(candidates)})")

        fin = get_financial(stock.code)

        fund = FundamentalData(
            pe=0, pb=0,
            roe=fin.get("roe", 0),
            revenue_growth=fin.get("revenue_growth", 0),
            profit_growth=fin.get("profit_growth", 0),
            gross_margin=fin.get("gross_margin", 0),
            debt_ratio=fin.get("debt_ratio", 0),
        )

        fund_score, fund_reasons = score_fundamental(
            fund.pe, fund.pb, fund.roe,
            fund.revenue_growth, fund.profit_growth, fund.debt_ratio,
        )

        total = tech_score * 0.6 + fund_score * 0.4

        results.append(ScreenerResult(
            stock=stock,
            tech=tech,
            fund=fund,
            screener_score=round(total, 1),
            screener_reasons=tech_reasons + fund_reasons,
        ))

    # Step 5: 排序返回 Top N
    results.sort(key=lambda r: r.screener_score, reverse=True)
    top_results = results[:top_n]

    # Step 6: 补充PE/PB估值数据
    if progress_callback:
        progress_callback(f"Agent A: 正在补充 {len(top_results)} 只股票的估值数据...")

    for r in top_results:
        try:
            info = get_stock_info(r.stock.code)
            if info["pe"] > 0:
                r.fund.pe = round(info["pe"], 1)
            if info["pb"] > 0:
                r.fund.pb = round(info["pb"], 2)
            # 如果stock list没拿到市值，用个股接口补充
            if r.stock.market_cap <= 0 and info["market_cap"] > 0:
                r.stock.market_cap = round(info["market_cap"], 1)
        except Exception:
            pass

    if progress_callback:
        progress_callback(f"Agent A: 筛选完成，共 {len(top_results)} 只进入候选池")

    return top_results
