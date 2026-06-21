# Orion Agent Runtime

一个基于 Python 的 AI Agent 运行时框架，采用 **Loop Engineering** 架构，支持 ReAct 内循环、目标验证闭环、幂等执行、安全护栏和完整的审计追踪。

## 🎯 核心特性

### 架构升级
- **ReAct 内循环** - Thought→Action→Observation 动态决策，替代静态规划
- **目标验证闭环** - verify→未达成则重规划，确保目标达成
- **Maker-Checker 分离** - 专用 LLM 角色配置，职责清晰
- **外部状态即真相源** - 进程崩溃可恢复，状态持久化

### 执行增强
- **幂等缓存** - 防止重复副作用，重试安全
- **MCP 长连接** - Session 复用，性能提升
- **强校验+强容错** - 参数验证、自动重试、失败重规划

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
│   ├── core/                      # 核心引擎
│   │   ├── workflow.py           # 主循环：ReAct/Plan→Execute + 收敛验证
│   │   ├── planner.py            # LLM 规划生成器（可选模式）
│   │   ├── executor.py           # 单步执行器（幂等缓存）
│   │   ├── react_loop.py         # ReAct 内循环实现
│   │   ├── goal_evaluator.py     # 目标验证器（Checker）
│   │   ├── skill_executor.py     # 技能执行器
│   │   ├── reviewer.py           # 结果审查器
│   │   ├── models.py             # 数据模型
│   │   ├── storage.py            # 状态持久化
│   │   ├── idempotency.py        # 幂等缓存管理
│   │   ├── stagnation_detector.py # 停滞检测
│   │   └── cost_guardrail.py     # 成本护栏
│   ├── llm_provider.py           # LLM 客户端工厂（maker/checker）
│   ├── config.py                 # 集中配置管理（环境变量）
│   ├── mcp/                      # MCP 协议集成
│   │   ├── mcp_config.py         # 服务器配置
│   │   └── mcp_manager.py        # 连接管理（长连接）
│   ├── safety/                   # 安全护栏（P5）
│   │   ├── guardrails.py         # 风险分级 + 人工批准
│   │   └── __init__.py
│   ├── audit/                    # 审计日志（P5）
│   │   ├── audit_log.py          # 结构化日志记录
│   │   └── __init__.py
│   ├── trace/                    # 追踪与调试
│   │   ├── trace_inspector.py
│   │   ├── run_inspector.py      # 状态查看
│   │   └── metrics_collector.py  # 指标收集（P5）
│   ├── tools/                    # 内置工具
│   │   ├── registry.py           # 工具注册表
│   │   ├── knowledge_tool.py     # 知识库查询
│   │   └── math_tool.py          # 数学计算
│   ├── memory/                   # 记忆系统
│   ├── knowledge/                # 知识库
│   └── skills/                   # 技能定义
├── tests/                        # 测试套件
│   ├── test_core.py
│   ├── test_idempotency.py
│   ├── test_goal_verification.py
│   ├── test_react_loop.py
│   ├── test_convergence_control.py
│   ├── test_guardrails.py        # P5 测试
│   └── test_audit_log.py         # P5 测试
├── verification/                 # 验收材料
│   ├── README.md
│   ├── verify.py                 # 快速验收脚本
│   ├── verify_e2e.py             # 端到端验收脚本
│   ├── VERIFICATION_CHECKLIST.md # 完整验收清单
│   └── ACCEPTANCE_REPORT.md      # 验收报告
├── pyproject.toml
└── README.md
```

## 🚀 快速开始

### 环境要求

- Python >= 3.10
- Node.js (用于 MCP filesystem server，可选)

### 安装

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate      # Windows
# 或
source .venv/bin/activate    # Linux/macOS

# 安装依赖
pip install -e ".[dev]"
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
    MCPServerConfig(
        name="git",
        command="uvx",
        args=["mcp-server-git"],
    ),
]
```

或通过环境变量：
```bash
export ORION_MCP_FILESYSTEM_DIRS="/path/to/folder1,/path/to/folder2"
```

### 运行

```bash
# 启动交互式 Agent
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

测试内容：
- ✅ 模块导入
- ✅ 配置加载
- ✅ 审计日志
- ✅ 安全护栏

### 端到端验收

```bash
python verification/verify_e2e.py
```

测试内容：
- ✅ 简单任务（直接回答）
- ✅ 工具调用任务
- ✅ 回滚功能
- ✅ 幂等性
- ✅ 安全护栏

### 运行测试套件

```bash
pytest tests/ -v
```

## 📈 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 工具调用延迟 | < 500ms | 本地计算工具 |
| 幂等缓存命中率 | > 80% | 同任务重试 |
| ReAct 循环平均迭代 | < 5 | 简单任务 |
| 审计日志写入 | < 10ms | 异步写入 |
| 状态恢复时间 | < 1s | 进程崩溃恢复 |

## 🔒 安全特性

### 风险分级

- **CRITICAL**：file_write, file_delete, execute_command 等
- **MEDIUM**：file_create, database_read, api_get 等
- **LOW**：math_add, text_search 等（自动批准）

### 人工批准

高风险操作需要人工确认：

```python
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

def my_tool_handler(args: MyToolArgs) -> str:
    return f"Result: {args.param1} + {args.param2}"

register_tool(
    name="my_tool",
    description="My custom tool",
    args_model=MyToolArgs,
    handler=my_tool_handler,
)
```

### 添加新技能

在 `src/orion_agent_runtime/skills/` 下创建新目录，包含 `SKILL.md`：

```markdown
# My Skill

## Description
Describe what this skill does.

## Input
- param1: description
- param2: description

## Output
Describe output format.
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

**状态**：✅ **P0-P5 全部完成，系统已就绪，可以投入生产使用！**

详细验收报告见 [verification/ACCEPTANCE_REPORT.md](verification/ACCEPTANCE_REPORT.md)