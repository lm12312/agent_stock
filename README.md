# A股双Agent智能选股系统

双Agent协作的A股智能筛选与推荐系统，集成 MiMo 大模型实现自然语言驱动选股。

## 系统架构

```
用户输入 → MiMo 大模型(调度中枢) → Agent A(筛选器) → Agent B(分析师) → 推荐结果
```

- **Agent A (筛选器)**：全市场扫描，技术面 + 基本面初筛，输出候选股票池
- **Agent B (分析师)**：对候选股做深度分析（技术形态 + 财务健康 + 动量），输出推荐信号与评分
- **MiMo 大模型**：理解用户意图、调度 Agent、解读分析结果、对话式交互

## 功能特性

- 自然语言对话选股（"帮我找低估值的消费股"）
- 实时扫描进度推送（SSE 流式）
- 多维评分体系：技术分(35%) + 基本面(35%) + 动量(30%)
- 推荐信号：强烈推荐 / 推荐 / 观望 / 回避
- 详细个股分析报告（技术指标、财务数据、风险提示）

## 技术栈

- **后端**: Python 3.10+, FastAPI, SSE
- **数据源**: akshare (新浪财经/网易财经)
- **LLM**: MiMo v2.5 (Anthropic 协议)
- **前端**: 原生 HTML/CSS/JS, Jinja2 模板

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制环境变量模板并填入你的 MiMo API Key：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```
MIMO_API_KEY=your_api_key_here
```

### 3. 启动服务

```bash
python main.py
```

访问 http://localhost:8000

## 项目结构

```
├── main.py              # FastAPI Web 入口
├── llm.py               # MiMo 大模型调度中枢
├── models.py            # 数据模型定义
├── agents/
│   ├── screener.py      # Agent A - 全市场筛选器
│   └── analyst.py       # Agent B - 深度分析师
├── data/
│   └── fetcher.py       # 数据获取层 (akshare)
├── templates/
│   └── index.html       # Web 前端模板
├── static/
│   └── style.css        # 样式文件
├── .env.example         # 环境变量模板
└── requirements.txt     # Python 依赖
```

## 使用方式

1. **手动扫描**：设置参数（推荐数量、最小市值、最大PE），点击启动扫描
2. **对话选股**：在对话框输入自然语言需求，MiMo 自动调度 Agent 完成筛选
3. **快捷指令**：点击预设按钮快速发起常见筛选场景
