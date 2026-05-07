"""
LLM 调度中枢 - 使用 Anthropic 协议接入 MiMo 大模型
职责：理解用户意图、调度 Agent A/B、解读分析结果、对话式交互
"""

import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(
    api_key=os.environ.get("MIMO_API_KEY", ""),
    base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
)

MODEL = "mimo-v2.5"

SYSTEM_PROMPT = """你是一个A股智能选股助手，背后有两个专业Agent协同工作：

- **Agent A（筛选器）**：全市场扫描，技术面+基本面初筛，输出候选股票池
- **Agent B（分析师）**：对候选股做深度分析，输出推荐信号和评分

## 你的能力
1. **调度Agent**：当用户要求选股/扫描/筛选时，调用 scan 工具启动 Agent A→B 流程
2. **解读结果**：拿到筛选结果后，用通俗语言解读每只股票的亮点和风险
3. **对话分析**：回答用户关于某只股票的追问，如"为什么推荐它？""风险在哪？"
4. **调整策略**：根据用户反馈调整筛选参数重新扫描

## 回复风格
- 简洁专业，用中文回复
- 涉及股票时给出代码+名称
- 分析要有依据（引用具体指标数值）
- 提示风险，不做投资建议承诺

## 可用工具
当用户要求扫描/筛选股票时，你必须调用 scan 工具。工具参数说明：
- top_n: 推荐数量，默认15
- min_mv: 最小市值(亿)，默认50
- max_pe: 最大PE，默认100
- industry: 行业筛选（可选），如"消费"、"科技"、"医药"
"""


def chat_stream(messages: list[dict], scan_results: list[dict] = None):
    """
    流式对话，返回生成器。
    messages: [{"role": "user"/"assistant", "content": "..."}]
    scan_results: 最近一次扫描结果，注入上下文供LLM分析
    """
    context = ""
    if scan_results:
        context = f"\n\n## 最近一次扫描结果（共{len(scan_results)}只）\n"
        context += "```json\n" + json.dumps(scan_results, ensure_ascii=False, indent=1) + "\n```\n"
        context += "请根据这些数据回答用户问题。如果用户没有指定股票，可以整体点评。"

    tools = [
        {
            "name": "scan",
            "description": "启动双Agent选股流程：Agent A全市场筛选 → Agent B深度分析。当用户要求扫描、筛选、推荐股票时调用此工具。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "推荐股票数量，默认15",
                    },
                    "min_mv": {
                        "type": "number",
                        "description": "最小市值(亿)，默认50",
                    },
                    "max_pe": {
                        "type": "number",
                        "description": "最大市盈率，默认100",
                    },
                    "industry": {
                        "type": "string",
                        "description": "行业筛选关键词，如消费、科技、医药、新能源等",
                    },
                },
            },
        }
    ]

    system = SYSTEM_PROMPT + context

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            tool_calls = []

            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls.append({
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_json": "",
                        })
                elif event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta":
                        yield {"type": "thinking", "data": event.delta.thinking}
                    elif event.delta.type == "text_delta":
                        yield {"type": "text", "data": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        if tool_calls:
                            tool_calls[-1]["input_json"] += event.delta.partial_json

            # 处理工具调用
            if tool_calls:
                for tc in tool_calls:
                    try:
                        args = json.loads(tc["input_json"]) if tc["input_json"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool_call", "id": tc["id"], "name": tc["name"], "args": args}

    except Exception as e:
        yield {"type": "error", "data": str(e)}


def build_tool_result_message(tool_call_id: str, results: list[dict]) -> dict:
    """构建工具调用结果消息，注入对话上下文"""
    summary = f"扫描完成，共找到 {len(results)} 只推荐股票。\n\n"
    for i, r in enumerate(results[:10], 1):
        summary += f"{i}. {r['code']} {r['name']} | 综合分:{r['total_score']} | 信号:{r['signal']} | PE:{r['pe']} | ROE:{r['roe']}%\n"
    if len(results) > 10:
        summary += f"...还有 {len(results)-10} 只\n"

    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": summary,
            }
        ],
    }


def continue_after_tool(messages: list[dict], scan_results: list[dict] = None):
    """工具调用后继续生成回复"""
    context = ""
    if scan_results:
        context = f"\n\n## 最近一次扫描结果\n```json\n{json.dumps(scan_results, ensure_ascii=False, indent=1)}\n```\n"

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT + context,
            messages=messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta":
                        yield {"type": "thinking", "data": event.delta.thinking}
                    elif event.delta.type == "text_delta":
                        yield {"type": "text", "data": event.delta.text}
    except Exception as e:
        yield {"type": "error", "data": str(e)}
