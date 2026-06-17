# Orion Agent Runtime

一个基于 Python 的 AI Agent 运行时框架，支持工具调用、MCP 协议集成、知识检索、技能执行和完整的执行追踪。

## 特性

- **智能规划器** — 自动分析用户输入并生成可执行的步骤计划
- **工具注册与调度** — 内置本地工具 + MCP (Model Context Protocol) 远程工具支持
- **知识库系统** — 文档加载、检索与上下文注入
- **记忆管理** — 任务摘要持久化，跨会话知识积累
- **技能执行器** — 通过 SKILL.md 定义可复用的复合技能（如生成日报、会议纪要）
- **执行追踪** — 完整的步骤级 Trace 记录与报告生成
- **容错机制** — 自动重试 (MAX_STEP_RETRIES=2) 和失败重规划 (MAX_REPLANS=2)

## 项目结构

```
orion-agent-runtime/
├── src/orion_agent_runtime/
│   ├── core/                  # 核心引擎
│   │   ├── workflow.py        # Agent 主循环：规划 → 执行 → 审查
│   │   ├── planner.py         # LLM 驱动的计划生成器
│   │   ├── executor.py        # 单步执行器
│   │   ├── skill_executor.py  # 技能执行器
│   │   ├── answer_synthesizer.py
│   │   ├── reviewer.py        # 结果审查器
│   │   ├── models.py          # 数据模型 (AgentState, Plan, Observation...)
│   │   └── storage.py         # 状态持久化
│   ├── llm_provider.py        # LLM 客户端 (OpenAI 兼容接口)
│   ├── mcp/                   # MCP 协议集成
│   │   ├── mcp_config.py      # 服务器配置
│   │   └── mcp_manager.py     # 连接管理 & 工具发现
│   ├── tools/                 # 内置工具
│   │   ├── registry.py        # 工具注册表
│   │   ├── knowledge_tool.py  # 知识库查询
│   │   └── math_tool.py       # 数学计算
│   ├── memory/                # 记忆系统
│   │   ├── memory.py          # MemoryManager
│   │   ├── memory_store.py    # 持久化存储
│   │   ├── memory_schema.py   # 记忆数据结构
│   │   └── memory_summarizer.py
│   ├── knowledge/             # 知识库
│   │   ├── loader.py
│   │   ├── retriever.py
│   │   └── documents/         # 知识文档目录
│   ├── skills/                # 技能定义
│   │   ├── generate-daily-report/
│   │   └── summarize-meeting/
│   ├── trace/                 # 追踪与调试
│   │   ├── trace_inspector.py
│   │   └── run_inspector.py
│   ├── utils/
│   └── benchmark/             # 基准测试套件
├── tests/
├── pyproject.toml
└── README.md
```

## 快速开始

### 环境要求

- Python >= 3.10
- Node.js (用于 MCP filesystem server)

### 安装

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# 或
.venv\Scripts\activate      # Windows

# 安装依赖
pip install -e ".[dev]"
```

### 运行

```bash
# 启动交互式 Agent
python -m orion_agent_runtime.main
```

交互界面示例：

```
> 帮我分析一下今天的代码提交记录
run_id: a1b2c3d4
status: done
result: ...

> exit
```

### 配置 LLM

编辑 `src/orion_agent_runtime/llm_provider.py`，修改 OpenAI 兼容接口的端点：

```python
client = OpenAI(
    base_url="https://your-api-endpoint/v1",
    api_key="your-api-key"
)
```

### 配置 MCP 服务器

编辑 `src/orion_agent_runtime/mcp/mcp_config.py`，添加或修改 MCP 服务器：

```python
MCP_SERVERS = [
    MCPServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"],
    ),
    MCPServerConfig(
        name="git",
        command="uvx",
        args=["mcp-server-git"],
    ),
]
```

## 核心架构

```
用户输入 → Planner (LLM) → Plan[步骤列表]
                              ↓
                    ┌─────────────────────┐
                    │   Agent Loop         │
                    │  current_step < len  │
                    │       plan           │
                    └─────────────────────┘
                              ↓
                    Executor (单步执行)
                    ├── 本地工具 (math, knowledge)
                    ├── MCP 远程工具 (git, filesystem)
                    └── 技能 (skill_executor)
                              ↓
                    Reviewer (结果审查)
                              ↓
                    Synthesizer (答案合成)
                              ↓
                         输出 / 重试
```

## 开发

### 运行测试

```bash
pytest tests/ -v
```

### 代码格式化

```bash
black src/
isort src/
```

### 状态存储

Agent 运行状态以 JSON 文件形式存储在 `runtime_state/` 目录下，可用于后续调试和追踪。

## License

MIT
