<div align="center">

# TokenTracker

**改一行 import，看清你的 LLM 账单花在了哪里。**

每次 API 调用自动记录。每分钱清晰可查。零配置。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/he-yufeng/TokenTracker/actions/workflows/ci.yml/badge.svg)](https://github.com/he-yufeng/TokenTracker/actions)

**[English](README.md) | [中文](README_CN.md)**

</div>

---

## 痛点

你在用 LLM 做开发，但不知道到底花了多少钱。月底 OpenAI 账单到了，比预期贵了 3 倍。你完全不知道是哪个功能、哪个模型、还是哪段 prompt 在烧钱。

现有方案要么是重量级平台（AgentOps、LangSmith），需要大改代码接入 SDK；要么只支持特定框架（LangChain、CrewAI）。

**TokenTracker** 的思路不一样：改一行 import，所有 API 调用自动追踪。不需要学新 SDK，不需要注册账号，不绑定任何框架。

## 快速上手

### 1. 安装

```bash
pip install tokentracker
```

### 2. 改一行 import

```diff
- from openai import OpenAI
+ from tokentracker import OpenAI
```

搞定。代码行为完全不变，但每次调用都会自动记录到本地 SQLite。

### 3. 看账单

```bash
tokentracker dashboard
```

```
╭──────────── TokenTracker — 最近 30 天 ──────────────╮
│ 总花费: $12.4832                                    
│ API 调用: 1,847 次                                  
│ Token: 2,391,205 (输入 1,843,901 / 输出 547,304)    
│ 平均延迟: 1,203ms                                    
│ 使用模型: 4 个                                       
╰────────────────────────────────────────────────────╯

         各模型开销
┌─────────────────┬───────┬───────────┬──────────┬─────────┐
│ 模型             │ 调用  │    Token  │   花费    │ 延迟     │
├─────────────────┼───────┼───────────┼──────────┼─────────┤
│ gpt-4o          │   312 │   892,104 │  $8.4210 │ 2,103ms │
│ claude-sonnet-4 │   201 │   634,882 │  $3.2015 │ 1,544ms │
│ gpt-4o-mini     │ 1,102 │   798,442 │  $0.7193 │   412ms │
│ deepseek-chat   │   232 │    65,777 │  $0.1414 │   891ms │
└─────────────────┴───────┴───────────┴──────────┴─────────┘
```

## 为什么用 TokenTracker？

| 特性 | TokenTracker | AgentOps | LangSmith | 手动打 log |
|------|:---:|:---:|:---:|:---:|
| 一行代码接入 | 是 | 否 | 否 | 否 |
| 不需要注册 | 是 | 否 | 否 | 是 |
| 数据留在本地 | 是 | 否 | 否 | 是 |
| 任何框架都能用 | 是 | 部分 | 否 | 是 |
| 自动算费用 | 是 | 是 | 是 | 否 |
| 终端仪表盘 | 是 | 否 | 否 | 否 |
| 永远免费 | 是 | 有限 | 有限 | 是 |

**TokenTracker 适合那些只想知道 LLM 花了多少钱、但不想接入一个平台的开发者。** 如果你需要团队协作、企业仪表盘，用 AgentOps 或 LangSmith。如果你只想看自己的钱花在哪了，用 TokenTracker。

## 用法

### Drop-in 客户端（同步 & 异步）

```python
# 同步
from tokentracker import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "你好"}]
)
# 自动记录: 模型、token 数、费用、延迟

# 异步
from tokentracker import AsyncOpenAI
client = AsyncOpenAI()
response = await client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "你好"}]
)
```

### 兼容 OpenRouter、Azure、Ollama — 任何 OpenAI 兼容接口

```python
from tokentracker import OpenAI

# OpenRouter（一个 key 用所有模型）
client = OpenAI(api_key="sk-or-...", base_url="https://openrouter.ai/api/v1")

# Azure OpenAI
client = OpenAI(api_key="...", base_url="https://your-resource.openai.azure.com/")

# Ollama（本地模型）
client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
```

### CLI 命令

```bash
# 仪表盘
tokentracker dashboard
tokentracker dashboard --days 7

# 最近的调用
tokentracker recent
tokentracker recent -n 50

# 导出数据
tokentracker export --format json > usage.json
tokentracker export --format csv > usage.csv

# 最近 7 天超过 $20 时让 CI 失败
tokentracker budget --days 7 --limit 20

# 脚本里用 JSON 输出
tokentracker budget --limit 100 --json
```

### Python 查询接口

```python
from tokentracker import summary, cost_by_model, cost_by_day, recent

# 总览
s = summary(days=30)
print(f"总花费: ${s['total_cost_usd']:.2f}")
print(f"总调用: {s['total_calls']}")

# 按模型拆分
for m in cost_by_model(days=7):
    print(f"  {m['model']}: ${m['total_cost']:.4f} ({m['calls']} 次)")

# 按天拆分
for d in cost_by_day(days=7):
    print(f"  {d['date']}: ${d['cost']:.4f}")
```

## 工作原理

TokenTracker 包装了 `openai.OpenAI` 客户端类。当你调用 `client.chat.completions.create()` 时，它：

1. 把调用原样传给真正的 OpenAI 客户端（不做任何修改）
2. 拿到响应后，从 `response.usage` 里提取 token 数量
3. 根据模型的单价表计算出费用（美元）
4. 把所有信息写入本地 SQLite（`~/.tokentracker/usage.db`）
5. 原样返回响应

没有代理，没有中间件，没有网络开销。就是一层薄薄的包装记录发生了什么。

## 支持的模型

TokenTracker 内置了 30+ 主流模型的定价，覆盖 OpenAI、Anthropic、Google、DeepSeek、Meta 等。如果你用的模型不在表里，调用仍然会被记录——只是费用栏会显示 "—" 而不是金额。

完整定价表见 [`tokentracker/pricing.py`](tokentracker/pricing.py)。欢迎提 PR 添加新模型。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `TOKENTRACKER_DB` | `~/.tokentracker/usage.db` | SQLite 数据库路径 |

就这一个配置项。其他全自动。

## 数据存储

所有数据存在本地 SQLite，不会发送到任何外部服务。你可以直接用 SQLite 工具查询：

```bash
sqlite3 ~/.tokentracker/usage.db "SELECT model, SUM(cost_usd) FROM calls GROUP BY model"
```

## 常见问题

**会拖慢 API 调用吗？**
不会。每次调用额外增加约 0.1ms（写一行 SQLite），而实际 API 调用本身需要 500-5000ms，追踪开销可以忽略不计。

**支持流式响应吗？**
token 数量从最终响应对象中提取。流式响应的自动追踪支持在 roadmap 中。

**能用在生产环境吗？**
可以。TokenTracker 使用线程安全的 SQLite 写入，开销极小。

**我的模型不在定价表里怎么办？**
调用仍然会完整记录（token 数、延迟等），只是费用字段为空。你可以在 `tokentracker/pricing.py` 里加上你的模型定价。

**可以追踪多个应用的费用吗？**
可以。默认所有应用写同一个数据库。需要分开的话，用 `TOKENTRACKER_DB` 环境变量给每个应用指定不同的数据库路径。

## 路线图

- [ ] 流式响应追踪
- [x] CLI 预算检查（日/月花费阈值）
- [ ] 费用告警（桌面 / 邮件 / Slack 通知）
- [ ] Embeddings 和图片 API 追踪
- [ ] 智能路由建议（检测可以用更便宜模型的请求）
- [ ] Web 仪表盘
- [ ] OpenTelemetry 导出

## 贡献

欢迎贡献，特别是：
- 添加新模型定价
- 支持更多 API 端点（embeddings、images、audio）
- 改进 CLI 仪表盘

## 许可证

[MIT](LICENSE)

---

<div align="center">

**如果 TokenTracker 帮你看清了 LLM 账单，给个 star！**

[报告问题](https://github.com/he-yufeng/TokenTracker/issues) · [功能建议](https://github.com/he-yufeng/TokenTracker/issues)

</div>
