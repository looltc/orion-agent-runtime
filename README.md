# Orion Agent Runtime

<p align="center">
  <strong>v0.1.0</strong> — Loop Engineering 架构 · Browser Use Agent · V2 Kernel
</p>

一个基于 Python 的 AI Agent 运行时框架，采用 **Loop Engineering** 架构，支持 ReAct 内循环、目标验证闭环、Browser Use 浏览器自动化、V2 异步 Kernel、幂等执行、安全护栏和完整的审计追踪。

## 🎯 核心特性

### 架构升级
- **ReAct 内循环** - Thought→Action→Observation 动态决策，替代静态规划
- **目标验证闭环** - verify→未达成则重规划，确保目标达成
- **Maker-Checker 分离** - 专用 LLM 角色配置，职责清晰
- **外部状态即真相源** - 进程崩溃可恢复，状态持久化

### Browser Use Agent
- **Playwright 驱动** - 基于 Playwright 的真实浏览器自动化
- **20+ 浏览器工具** - 导航、点击、输入、截图、JS执行等全套操作
- **智能内容提取** - iframe 遍历、语义化区域检测、SPA 内容稳定性等待
- **Mock 模式** - 完整的 MockBrowserCapability 支持无头测试
- **多标签页管理** - 新建、切换、关闭标签页

### V2 Kernel 架构
- **能力层 (Capabilities)** - 浏览器、桌面等独立能力模块，热插拔设计
- **事件总线 (EventBus)** - 组件间异步通信 + JSONL 持久化
- **异步运行时 (AgentRuntime)** - 原生 async/await 执行引擎
- **任务调度器 (Scheduler)** - 异步任务编排与并发控制
- **世界状态 (WorldState)** - Agent 感知的外部环境建模
- **三层记忆** - Episodic（情景）、Semantic（语义）、Working（工作）记忆分层

### 执行增强
- **幂等缓存** - 防止重复副作用，重试安全
- **MCP 长连接** - Session 复用，性能提升
- **强校验+强容错** - 参数验证、自动重试、失败重规划
- **异步工具支持** - V1 executor 支持异步工具处理

### 可观测性与安全
- **完整审计日志** - 所有关键事件结构化记录
- **指标收集** - Token 消耗、迭代次数、工具调用统计
- **安全护栏** - 风险分级（CRITICAL/MEDIUM/LOW）+ 人工批准
- **停滞检测** - 防止无限循环，智能暂停
- **成本护栏** - Token 预算控制

### 原有功能保留
- **智能规划器** - 自动分析用户输入并生成可执行步骤（可选）
- **工具注册与调度** - 本地工具 + MCP 远程工具
- **知识库系统** - 文档加载、检索与上下文注入
- **记忆管理** - 任务摘要持久化，跨会话知识积累
- **技能执行器** - 通过 SKILL.md 定义可复用复合技能

## 📁 项目结构

```
orion-agent-runtime/
├── src/orion_agent_runtime/
│   ├── main.py                   # 入口：V1 交互式 + V2 Kernel 启动
│   ├── config.py                 # 集中配置管理（环境变量）
│   ├── llm_provider.py          # LLM 客户端工厂（maker/checker）
│   │
│   ├── core/                     # V1 核心引擎
│   │   ├── workflow.py           # 主循环：ReAct/Plan→Execute + 收敛验证
│   │   ├── planner.py            # LLM 规划生成器（可选模式）
│   │   ├── executor.py           # 单步执行器（幂等缓存 + 异步支持）
│   │   ├── react_loop.py         # ReAct 内循环实现
│   │   ├── goal_evaluator.py     # 目标验证器（Checker）
│   │   ├── skill_executor.py     # 技能执行器
│   │   ├── reviewer.py           # 结果审查器
│   │   ├── models.py             # 数据模型
│   │   ├── storage.py            # 状态持久化
│   │   ├── idempotency.py        # 幂等缓存管理
│   │   ├── stagnation_detector.py # 停滞检测
│   │   └── cost_guardrail.py     # 成本护栏
│   │
│   ├── kernel/                   # V2 内核
│   │   └── kernel.py             # Kernel 核心（能力注册、生命周期管理）
│   │
│   ├── capabilities/             # V2 能力层
│   │   ├── base.py              # Capability 基类 + Registry
│   │   ├── browser/             # 浏览器能力
│   │   │   ├── capability.py    # Playwright 浏览器驱动
│   │   │   ├── extractor.py     # 智能页面内容提取
│   │   │   └── mock.py          # Mock 浏览器（测试用）
│   │   └── desktop/             # 桌面自动化能力
│   │       ├── capability.py    # 桌面驱动
│   │       └── mock.py          # Mock 桌面
│   │
│   ├── tools/                    # 工具注册表
│   │   ├── registry.py          # 工具注册中心
│   │   ├── browser_tools.py     # 20+ LLM-callable 浏览器工具
│   │   ├── knowledge_tool.py     # 知识库查询
│   │   └── math_tool.py         # 数学计算
│   │
│   ├── bus/                      # V2 事件总线
│   │   ├── event.py             # 事件模型
│   │   └── event_bus.py         # EventBus + JSONL 持久化
│   │
│   ├── runtime/                  # V2 异步运行时
│   │   ├── agent_runtime.py     # 异步 AgentRuntime
│   │   └── executor_async.py    # 异步执行器
│   │
│   ├── scheduler/               # V2 调度器
│   │   ├── scheduler.py         # 异步任务调度
│   │   └── task.py              # 任务模型
│   │
│   ├── world/                    # V2 世界状态
│   │   ├── state.py             # WorldState 模型
│   │   └── world_manager.py     # 世界状态管理器
│   │
│   ├── memory/                   # 记忆系统
│   │   ├── memory.py            # 记忆管理器
│   │   ├── memory_schema.py     # 记忆数据模型
│   │   ├── memory_store.py      # 记忆存储
│   │   ├── episodic/            # 情景记忆
│   │   ├── semantic/            # 语义记忆
│   │   └── working/             # 工作记忆
│   │
│   ├── mcp/                      # MCP 协议集成
│   │   ├── mcp_config.py         # 服务器配置
│   │   └── mcp_manager.py        # 连接管理（长连接）
│   │
│   ├── safety/                   # 安全护栏
│   │   └── guardrails.py         # 风险分级 + 人工批准
│   │
│   ├── audit/                    # 审计日志
│   │   └── audit_log.py          # 结构化日志记录
│   │
│   ├── trace/                    # 追踪与调试
│   │   ├── trace_inspector.py
│   │   ├── run_inspector.py      # 状态查看
│   │   └── metrics_collector.py  # 指标收集
│   │
│   ├── knowledge/                # 知识库
│   └── skills/                   # 技能定义
├── tests/                        # 测试套件
├── verification/                 # 验收材料
├── pyproject.toml
└── README.md
```

## 🚀 快速开始

### 环境要求

- Python >= 3.10
- Node.js (用于 MCP filesystem server，可选)
- Playwright (用于 Browser Use Agent，可选)

### 安装

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate      # Windows
# 或
source .venv/bin/activate    # Linux/macOS

# 安装依赖
pip install -e ".[dev]"

# 安装浏览器（Browser Use Agent）
playwright install chromium
```

### 配置 LLM

通过环境变量配置 LLM 端点：

```bash
export ORION_LLM_BASE_URL="http://localhost:1234/v1"
export ORION_LLM_API_KEY="your-api-key"
export ORION_LLM_MODEL="local-model"

# 可选：配置 Checker LLM（目标验证专用）
export ORION_CHECKER_LLM_BASE_URL="http://localhost:1234/v1"
export ORION_CHECKER_LLM_MODEL="local-model"
```

### 配置 MCP 服务器

编辑 `src/orion_agent_runtime/mcp/mcp_config.py` 或通过环境变量：

```python
MCP_SERVERS = [
    MCPServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/path/to/folder"],
    ),
]
```

或通过环境变量：
```bash
export ORION_MCP_FILESYSTEM_DIRS="/path/to/folder1,/path/to/folder2"
```

### 运行

```bash
# 启动交互式 Agent（V1 模式）
python -m orion_agent_runtime.main
```

交互界面示例：

```
> 计算 25 * 4
run_id: abc123
status: goal_achieved
result: 25与4的乘积是100。

> exit
```

## 🌐 Browser Use Agent

Orion 内置了完整的浏览器自动化能力，LLM 可通过 20+ 浏览器工具操控真实网页：

### 可用工具

| 工具 | 说明 |
|------|------|
| `browser_open` | 启动浏览器 |
| `browser_navigate` | 导航到指定 URL |
| `browser_click` | 点击页面元素 |
| `browser_type` | 在输入框中输入文本 |
| `browser_snapshot` | 获取页面快照（文本+链接+按钮+输入框） |
| `browser_get_page_text` | 提取页面全部文本内容 |
| `browser_get_links` | 获取页面所有链接 |
| `browser_screenshot` | 截取页面截图 |
| `browser_scroll` | 滚动页面 |
| `browser_evaluate_js` | 执行 JavaScript |
| `browser_new_tab` / `browser_switch_tab` / `browser_close_tab` | 标签页管理 |
| `browser_go_back` / `browser_go_forward` | 前进/后退 |
| `browser_wait` | 等待指定时间或条件 |
| `browser_press_key` / `browser_select_option` / `browser_hover` | 高级交互 |
| `browser_close` | 关闭浏览器 |

### 智能内容提取

- **iframe 遍历** — 自动进入页面内 iframe 提取内容
- **语义区域检测** — 优先提取 `<main>`、`<article>`、`#content` 等语义化区域
- **SPA 稳定性等待** — 检测内容停止变化后再提取，避免空白快照
- **networkidle 回退** — 先尝试 `networkidle` 等待策略，失败回退到 `domcontentloaded`

### 配置

```bash
# 浏览器模式（headless / headed）
export ORION_BROWSER_MODE="headless"

# 是否无头（便捷开关）
export ORION_BROWSER_HEADLESS="true"

# 页面加载超时（毫秒）
export ORION_BROWSER_TIMEOUT="30000"
```

## 🏗️ V2 Kernel 架构

V2 架构在 V1 核心引擎基础上，引入了模块化内核设计：

```
V2 Kernel
├── CapabilityRegistry    ← 能力注册中心（热插拔）
├── EventBus             ← 异步事件总线 + JSONL 持久化
├── WorldState           ← Agent 感知的外部环境
├── Memory 三层架构
│   ├── EpisodicStore    ← 情景记忆（what happened）
│   ├── SemanticStore    ← 语义记忆（what I know）
│   └── WorkingStore     ← 工作记忆（what I'm doing now）
├── Scheduler            ← 异步任务调度
└── AgentRuntime         ← 异步运行时引擎
```

### 能力层 (Capabilities)

Capabilities 是对底层驱动的抽象封装，支持热插拔注册：

```python
from orion_agent_runtime.capabilities.base import Capability, CapabilityRegistry

class BrowserCapability(Capability):
    async def open(self): ...
    async def snapshot(self): ...
    async def close(self): ...

# 注册到全局 Registry
registry = get_registry()
registry.register(browser_cap)
```

### 事件总线 (EventBus)

组件间通过 EventBus 异步通信，所有事件持久化到 JSONL 文件：

```python
bus = EventBus()
await bus.emit("browser.page_loaded", {"url": url, "title": title})
await bus.emit("tool.called", {"tool": "click", "args": {...}})
```

## 🔧 高级配置

### 环境变量列表

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `ORION_LLM_BASE_URL` | LLM API 端点 | `http://localhost:1234/v1` |
| `ORION_LLM_API_KEY` | LLM API 密钥 | `local-1234567890abcdef` |
| `ORION_LLM_MODEL` | LLM 模型名称 | `local-model` |
| `ORION_CHECKER_LLM_BASE_URL` | Checker LLM 端点 | 同主 LLM |
| `ORION_CHECKER_LLM_API_KEY` | Checker LLM 密钥 | 同主 LLM |
| `ORION_CHECKER_LLM_MODEL` | Checker LLM 模型 | 同主 LLM |
| `ORION_RUNTIME_STATE_DIR` | 运行时状态目录 | `./runtime_state` |
| `ORION_MCP_FILESYSTEM_DIRS` | MCP 文件系统目录 | `无` |
| `ORION_BROWSER_MODE` | 浏览器模式 | `headless` |
| `ORION_BROWSER_HEADLESS` | 是否无头运行 | `true` |
| `ORION_BROWSER_TIMEOUT` | 浏览器超时(ms) | `30000` |
| `ORION_AUTO_APPROVE` | 自动批准高风险操作 | `false` |
| `ORION_APPROVAL_TIMEOUT` | 批准超时时间（秒） | `300` |

### 回滚开关

如需回退到旧模式，可在 `src/orion_agent_runtime/core/workflow.py` 中修改：

```python
# 关闭 ReAct 内循环，回归 Plan→Execute 模式
USE_REACT_LOOP = False

# 关闭目标验证，执行完成即 done
VERIFY_ON_FINISH = False
```

## 📊 核心架构

### Loop Engineering 架构

```
用户输入
    ↓
Planner（可选初始化）
    ↓
┌─────────────────────────────────────┐
│        ReAct 内循环（默认）          │
│  ┌───────────────────────────────┐  │
│  │ LLM 决策 → 执行工具 → 观察    │  │
│  │   ↑                          │  │
│  │   └── 回灌观察结果            │  │
│  │  （最多 MAX_ITERATIONS 次）    │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
    ↓
目标验证（Checker）
    ↓
┌─────────────────────────────────────┐
│         收敛闭环                     │
│  未达成 → 重规划 → 再执行 → 再验证  │
│  （最多 MAX_GOAL_EVALUATIONS 次）   │
└─────────────────────────────────────┘
    ↓
goal_achieved / failed
```

### Maker-Checker 分离

- **Maker LLM**：负责工具决策、步骤执行
- **Checker LLM**：负责目标验证、结果评估
- **好处**：职责清晰，可使用不同模型，提高可靠性

## 🧪 验收与测试

### 快速验收

```bash
python verification/verify.py
```

### 运行测试套件

```bash
pytest tests/ -v
```

测试覆盖：
- ✅ V1 核心引擎（workflow、react_loop、executor、planner）
- ✅ 幂等缓存、目标验证、收敛控制、停滞检测
- ✅ 安全护栏、审计日志
- ✅ Browser Use（工具注册、Mock 模式、内容提取）
- ✅ V2 模块（EventBus、Capabilities、Kernel、Memory、Scheduler、World）

## 📈 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 工具调用延迟 | < 500ms | 本地计算工具 |
| 幂等缓存命中率 | > 80% | 同任务重试 |
| ReAct 循环平均迭代 | < 5 | 简单任务 |
| 审计日志写入 | < 10ms | 异步写入 |
| 状态恢复时间 | < 1s | 进程崩溃恢复 |
| SPA 内容提取 | < 5s | 含稳定性等待 |

## 🔒 安全特性

### 风险分级

- **CRITICAL**：file_write, file_delete, execute_command 等
- **MEDIUM**：file_create, database_read, api_get 等
- **LOW**：math_add, text_search 等（自动批准）

### 人工批准

高风险操作需要人工确认：

```bash
# 设置环境变量启用自动批准（测试环境）
export ORION_AUTO_APPROVE=true
```

### 审计日志

所有操作记录在 `runtime_state/audit.jsonl`，包括：
- 任务开始/完成/失败
- 工具调用（开始/成功/失败/缓存命中）
- 目标验证（开始/完成/失败）
- 人工批准（批准/拒绝）
- 成本超限、停滞检测

## 📚 开发指南

### 添加新工具

```python
from pydantic import BaseModel
from orion_agent_runtime.tools.registry import register_tool

class MyToolArgs(BaseModel):
    param1: str
    param2: int = 42

async def my_tool_handler(param1: str, param2: int = 42) -> str:
    return f"Result: {param1} + {param2}"

register_tool(
    name="my_tool",
    description="My custom tool",
    args_model=MyToolArgs,
    handler=my_tool_handler,  # 支持同步和异步
)
```

### 添加新能力

```python
from orion_agent_runtime.capabilities.base import Capability, CapabilityResult, get_registry

class MyCapability(Capability):
    name = "my_capability"

    async def open(self) -> CapabilityResult: ...
    async def snapshot(self) -> CapabilityResult: ...
    async def close(self) -> CapabilityResult: ...

# 注册
registry = get_registry()
registry.register(MyCapability())
```

### 查看运行状态

```bash
python -m orion_agent_runtime.trace.run_inspector
```

## 📄 License

MIT

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**版本**：[v0.1.0](https://github.com/looltc/orion-agent-runtime/releases/tag/v0.1.0) | **分支**：[`main`](https://github.com/looltc/orion-agent-runtime/tree/main) / [`dev-aicoding-glm`](https://github.com/looltc/orion-agent-runtime/tree/dev-aicoding-glm)
