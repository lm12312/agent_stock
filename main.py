"""
A股双Agent智能选股系统 - FastAPI Web入口
Agent A (筛选器) + Agent B (分析师) + LLM 调度中枢
"""

import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from concurrent.futures import ThreadPoolExecutor

from agents.screener import run_screener
from agents.analyst import run_analyst
from models import Signal
from llm import chat_stream, build_tool_result_message, continue_after_tool

app = FastAPI(title="A股双Agent智能选股")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

executor = ThreadPoolExecutor(max_workers=4)

SIGNAL_COLORS = {
    Signal.STRONG_BUY: "#e74c3c",
    Signal.BUY: "#e67e22",
    Signal.HOLD: "#f1c40f",
    Signal.AVOID: "#95a5a6",
}

SIGNAL_BADGES = {
    Signal.STRONG_BUY: "强烈推荐",
    Signal.BUY: "推荐",
    Signal.HOLD: "观望",
    Signal.AVOID: "回避",
}

last_scan_results = []


def _format_result(r) -> dict:
    return {
        "code": r.screener.stock.code,
        "name": r.screener.stock.name,
        "market_cap": round(r.screener.stock.market_cap, 1),
        "price": round(r.screener.tech.price, 2),
        "change_pct": round(r.screener.tech.change_pct, 2),
        "pe": round(r.screener.fund.pe, 1),
        "pb": round(r.screener.fund.pb, 2),
        "roe": round(r.screener.fund.roe, 1),
        "rsi": round(r.screener.tech.rsi, 1),
        "tech_score": r.tech_score,
        "fund_score": r.fund_score,
        "momentum_score": r.momentum_score,
        "total_score": r.total_score,
        "signal": SIGNAL_BADGES.get(r.signal, "观望"),
        "signal_color": SIGNAL_COLORS.get(r.signal, "#f1c40f"),
        "reasons": r.reasons[:8],
        "risks": r.risks[:5],
    }


async def _run_screener_async(top_n, min_mv, max_pe, q: asyncio.Queue):
    """在线程池中运行 screener，通过队列实时推送进度"""
    loop = asyncio.get_event_loop()

    def progress(msg):
        loop.call_soon_threadsafe(q.put_nowait, msg)

    candidates = await loop.run_in_executor(
        executor,
        lambda: run_screener(top_n=top_n, min_market_cap=min_mv, max_pe=max_pe, progress_callback=progress),
    )
    return candidates


async def _run_analyst_async(candidates, q: asyncio.Queue):
    """在线程池中运行 analyst，通过队列实时推送进度"""
    loop = asyncio.get_event_loop()

    def progress(msg):
        loop.call_soon_threadsafe(q.put_nowait, msg)

    results = await loop.run_in_executor(
        executor,
        lambda: run_analyst(candidates, progress_callback=progress),
    )
    return results


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/scan")
async def scan(top_n: int = 15, min_mv: float = 50, max_pe: float = 100):
    """SSE流式接口：Agent A筛选 → Agent B分析，实时推送进度"""

    async def event_stream():
        global last_scan_results
        q = asyncio.Queue()

        yield _sse({"type": "progress", "data": "🚀 Agent A 启动：全市场扫描开始..."})

        # 启动 screener，进度通过队列实时推送
        screener_task = asyncio.create_task(_run_screener_async(top_n, min_mv, max_pe, q))

        while not screener_task.done() or not q.empty():
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield _sse({"type": "progress", "data": msg})
            except asyncio.TimeoutError:
                # 没有新消息，继续等待
                if screener_task.done():
                    break

        candidates = screener_task.result()

        # 排空队列中剩余消息
        while not q.empty():
            yield _sse({"type": "progress", "data": q.get_nowait()})

        if not candidates:
            yield _sse({"type": "progress", "data": "⚠️ Agent A 未找到符合条件的股票"})
            yield _sse({"type": "done", "data": []})
            return

        yield _sse({
            "type": "progress",
            "data": f"✅ Agent A 完成：{len(candidates)} 只股票进入候选池，交给 Agent B 深度分析..."
        })

        candidate_info = [{"code": c.stock.code, "name": c.stock.name, "score": c.screener_score} for c in candidates]
        yield _sse({"type": "candidates", "data": candidate_info})

        # 启动 analyst，进度通过队列实时推送
        analyst_task = asyncio.create_task(_run_analyst_async(candidates, q))

        while not analyst_task.done() or not q.empty():
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield _sse({"type": "progress", "data": msg})
            except asyncio.TimeoutError:
                if analyst_task.done():
                    break

        results = analyst_task.result()

        while not q.empty():
            yield _sse({"type": "progress", "data": q.get_nowait()})

        final = [_format_result(r) for r in results]
        last_scan_results = final

        yield _sse({"type": "progress", "data": f"✅ Agent B 完成：共推荐 {len(final)} 只股票"})
        yield _sse({"type": "result", "data": final})
        yield _sse({"type": "done", "data": []})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat")
async def chat(request: Request):
    """对话接口：LLM 调度中枢，支持工具调用驱动 Agent A/B"""
    try:
        body = await request.json()
    except Exception:
        return StreamingResponse(
            iter([_sse({"type": "error", "data": "无效的请求格式"})]),
            media_type="text/event-stream",
        )
    messages = body.get("messages", [])

    async def event_stream():
        global last_scan_results
        loop = asyncio.get_event_loop()

        # 调用 LLM
        full_text = ""
        thinking_text = ""
        tool_calls_info = []

        try:
            llm_chunks = await loop.run_in_executor(
                executor,
                lambda: list(chat_stream(messages, last_scan_results if last_scan_results else None)),
            )
        except Exception as e:
            yield _sse({"type": "error", "data": f"LLM调用失败: {str(e)}"})
            yield _sse({"type": "done"})
            return

        for chunk in llm_chunks:
            if chunk["type"] == "thinking":
                thinking_text += chunk["data"]
                yield _sse({"type": "thinking", "data": chunk["data"]})
            elif chunk["type"] == "text":
                full_text += chunk["data"]
                yield _sse({"type": "text", "data": chunk["data"]})
            elif chunk["type"] == "tool_call":
                tool_calls_info.append(chunk)
            elif chunk["type"] == "error":
                yield _sse({"type": "error", "data": chunk["data"]})
                yield _sse({"type": "done"})
                return

        # 如果有工具调用（scan），执行 Agent A→B 流程
        if tool_calls_info:
            for tc in tool_calls_info:
                if tc["name"] == "scan":
                    args = tc["args"]
                    top_n = args.get("top_n", 15)
                    min_mv = args.get("min_mv", 50)
                    max_pe = args.get("max_pe", 100)

                    yield _sse({"type": "progress", "data": "🔧 MiMo 决定调用选股工具，启动 Agent A..."})

                    q = asyncio.Queue()

                    # Agent A
                    screener_task = asyncio.create_task(_run_screener_async(top_n, min_mv, max_pe, q))

                    while not screener_task.done() or not q.empty():
                        try:
                            msg = await asyncio.wait_for(q.get(), timeout=0.5)
                            yield _sse({"type": "progress", "data": msg})
                        except asyncio.TimeoutError:
                            if screener_task.done():
                                break

                    candidates = screener_task.result()

                    while not q.empty():
                        yield _sse({"type": "progress", "data": q.get_nowait()})

                    if not candidates:
                        yield _sse({"type": "progress", "data": "⚠️ 未找到符合条件的股票"})
                        yield _sse({"type": "done"})
                        return

                    yield _sse({"type": "progress", "data": f"✅ Agent A 完成：{len(candidates)} 只候选，交给 Agent B..."})

                    candidate_info = [{"code": c.stock.code, "name": c.stock.name, "score": c.screener_score} for c in candidates]
                    yield _sse({"type": "candidates", "data": candidate_info})

                    # Agent B
                    analyst_task = asyncio.create_task(_run_analyst_async(candidates, q))

                    while not analyst_task.done() or not q.empty():
                        try:
                            msg = await asyncio.wait_for(q.get(), timeout=0.5)
                            yield _sse({"type": "progress", "data": msg})
                        except asyncio.TimeoutError:
                            if analyst_task.done():
                                break

                    results = analyst_task.result()

                    while not q.empty():
                        yield _sse({"type": "progress", "data": q.get_nowait()})

                    final = [_format_result(r) for r in results]
                    last_scan_results = final
                    yield _sse({"type": "result", "data": final})
                    yield _sse({"type": "progress", "data": "✅ Agent B 完成，正在生成分析报告..."})

                    # 把工具结果注入对话，让 LLM 生成解读
                    tool_msg = build_tool_result_message(tc["id"], final)
                    messages.append({"role": "assistant", "content": f"我来调用选股工具为你分析。"})
                    messages.append(tool_msg)

                    for chunk in await loop.run_in_executor(
                        executor,
                        lambda: list(continue_after_tool(messages, final)),
                    ):
                        if chunk["type"] == "thinking":
                            yield _sse({"type": "thinking", "data": chunk["data"]})
                        elif chunk["type"] == "text":
                            yield _sse({"type": "text", "data": chunk["data"]})
                        elif chunk["type"] == "error":
                            yield _sse({"type": "error", "data": chunk["data"]})

        yield _sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
