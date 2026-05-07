import os
os.environ["TQDM_DISABLE"] = "1"

import json
import pandas as pd
import requests
from models import StockBasic
import time

# akshare在模块加载时导入（V8引擎需要在主线程初始化，避免多线程崩溃）
import akshare as ak

_stock_list_cache = None
_stock_list_time = 0
_stock_info_cache = {}  # code -> {pe, pb, market_cap}


def _code_to_symbol(code: str) -> str:
    """纯数字代码转带前缀格式: 000001 -> sz000001, 600519 -> sh600519"""
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith(("0", "2", "3")):
        return f"sz{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _pure_code(code: str) -> str:
    """去掉前缀: sh600519 -> 600519"""
    if code.startswith(("sh", "sz", "bj")):
        return code[2:]
    return code


def get_stock_list() -> list[StockBasic]:
    """获取A股列表（新浪扩展API），包含PE、PB、市值"""
    global _stock_list_cache, _stock_list_time, _stock_info_cache
    now = time.time()
    if _stock_list_cache is not None and now - _stock_list_time < 600:
        return _stock_list_cache

    stocks = []
    _stock_info_cache = {}
    try:
        # 使用新浪扩展行情API，自带PE/PB/市值
        all_data = []
        for page in range(1, 200):  # 最多200页
            try:
                url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
                params = {
                    "page": page,
                    "num": 80,
                    "sort": "symbol",
                    "asc": 1,
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "init",
                }
                r = requests.get(url, params=params, timeout=10,
                                 headers={"Referer": "https://finance.sina.com.cn"})
                data = json.loads(r.text)
                if not data:
                    break
                all_data.extend(data)
            except Exception:
                break

        print(f"[Fetcher] 新浪扩展API: {len(all_data)} 条")

        for item in all_data:
            code = str(item.get("code", ""))
            name = str(item.get("name", ""))
            price = float(item.get("trade", 0) or 0)
            pe = float(item.get("per", 0) or 0)
            pb = float(item.get("pb", 0) or 0)
            mktcap = float(item.get("mktcap", 0) or 0) / 10000  # 万元->亿

            pure = _pure_code(code)
            if pure.startswith(("4", "8", "920")):
                continue
            if "ST" in name or "退" in name:
                continue
            if price <= 0:
                continue

            stocks.append(StockBasic(
                code=pure,
                name=name,
                market_cap=round(mktcap, 1),
            ))
            # 缓存PE/PB数据
            _stock_info_cache[pure] = {
                "pe": pe if pe > 0 else 0,
                "pb": pb if pb > 0 else 0,
                "market_cap": round(mktcap, 1),
            }

    except Exception as e:
        print(f"[Fetcher] 获取股票列表失败: {e}")
        # 回退到akshare
        try:
            df = ak.stock_zh_a_spot()
            for _, row in df.iterrows():
                code = str(row.iloc[0])
                name = str(row.iloc[1])
                price = float(row.iloc[2] or 0)
                pure = _pure_code(code)
                if pure.startswith(("4", "8", "920")):
                    continue
                if "ST" in name or "退" in name:
                    continue
                if price <= 0:
                    continue
                stocks.append(StockBasic(code=pure, name=name))
        except Exception as e2:
            print(f"[Fetcher] 回退也失败: {e2}")

    _stock_list_cache = stocks
    _stock_list_time = now
    print(f"[Fetcher] 有效股票: {len(stocks)} 只")
    return stocks


def get_stock_info(code: str) -> dict:
    """获取单只股票的PE、PB、市值（从缓存查找）"""
    result = {"pe": 0.0, "pb": 0.0, "market_cap": 0.0}
    if code in _stock_info_cache:
        return _stock_info_cache[code]
    return result


def get_kline(code: str, days: int = 120) -> pd.DataFrame:
    """获取K线数据（网易源）"""
    symbol = _code_to_symbol(code)
    start = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")

    try:
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust="qfq")
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={
            "date": "date", "open": "open", "close": "close",
            "high": "high", "low": "low", "volume": "volume",
            "amount": "amount",
        })
        for col in ["open", "close", "high", "low", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "close" in df.columns and len(df) > 1:
            df["change_pct"] = df["close"].pct_change() * 100

        return df
    except Exception:
        return pd.DataFrame()


def get_financial(code: str) -> dict:
    """获取财务指标（基于已有数据源，不使用py_mini_racer）"""
    result = {"roe": 0, "gross_margin": 0, "revenue_growth": 0, "profit_growth": 0, "debt_ratio": 0}

    # 尝试从缓存的stock_info中获取PE/PB相关的基础数据
    # ROE等指标暂时返回0，fundamental评分将主要基于PE/PB
    return result


