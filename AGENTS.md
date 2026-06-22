# Orion Agent Runtime — AI Agent 开发指南

## 项目概述

Orion Agent Runtime 是一个基于 Python 的 AI Agent 运行时框架，核心流程为 **规划 → 执行 → 审查**，支持 ReAct 内循环、MCP 远程工具、知识库检索、记忆管理和完整追踪。

## 快速命令

```bash
# 安装（含开发依赖）
pip install -e ".[dev]"

# 运行交互式 Agent
python -m orion_agent_runtime.main

# 运行测试
pytest tests/ -v

# 代码格式化
black src/ tests/
isort src/ tests/
```

## 关键环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ORION_LLM_BASE_URL` | LLM API 端点 | `http://localhost:1234/v1` |
| `ORION_LLM_API_KEY` | API Key | `lm-studio` |
| `ORION_LLM_MODEL` | 模型名 | `lmstudio-community/Qwen2.5-7B-Instruct-GGUF` |
| `ORION_RUNTIME_STATE_DIR` | 运行时状态目录 | `runtime_state/` |
| `ORION_MCP_FILESYSTEM_DIRS` | MCP 文件系统允许路径 | 空（不启用） |

## 架构概览

```
main.py (入口)
  └── workflow.py (主循环)
        ├── planner.py → Plan (LLM 生成步骤计划)
        ├── executor.py → 单步工具执行 (含幂等+审计)
        ├── react_loop.py → ReAct 推理-行动-观察循环
        ├── goal_evaluator.py → 目标达成验证
        ├── answer_synthesizer.py → 答案合成
        ├── reviewer.py → 结果审查
        └── skill_executor.py → 技能执行

tools/registry.py → 工具注册中心 (本地 + MCP)
mcp/mcp_manager.py → MCP 服务器连接 & 工具发现
memory/memory.py → MemoryManager (记忆存取)
knowledge/ → 文档加载 & 检索
skills/ → SKILL.md 定义的可复用技能
audit/ → 审计日志
safety/guardrails.py → 安全护栏
trace/ → 执行追踪与报告
benchmark/ → 基准测试套件
```

## 核心数据模型 (`core/models.py`)

- `Plan` — 包含 goal、success_criteria、steps 的计划
- `PlanStep` — 单步：tool + arguments
- `ReactAction` — ReAct 单步决策 (call_tool / finish)
- `AgentState` — Agent 运行时状态
- `ExecutionTrace` — 单步执行轨迹
- `ToolSpec` — 工具描述 (name, description, origin, handler)

## 开发约定

### 新增本地工具

在 `tools/registry.py` 中用 `@register_tool` 装饰器注册：

```python
from orion_agent_runtime.tools.registry import register_tool

@register_tool("my_tool", "工具描述")
class MyArgs(BaseModel):
    param: str

def my_tool_impl(param: str) -> str:
    return f"结果: {param}"
```

### 新增技能

在 `skills/` 下创建目录，包含 `SKILL.md`（YAML frontmatter + 处理规则）。

### 配置 LLM

通过环境变量或编辑 `llm_provider.py` 中的默认值。maker/checker 角色通过 `get_llm_client(role=...)` 区分。

### 测试

测试文件在 `tests/` 下，按功能模块命名（如 `test_core.py`、`test_audit_log.py`）。

## 常见开发任务

| 任务 | 涉及文件 |
|------|----------|
| 修改 LLM 端点 | `config.py` (环境变量) 或 `llm_provider.py` |
| 新增工具 | `tools/registry.py` + 实现文件 |
| 修改规划逻辑 | `core/planner.py` |
| 修改执行循环 | `core/workflow.py`, `core/executor.py`, `core/react_loop.py` |
| 修改目标验证 | `core/goal_evaluator.py` |
| 新增记忆类型 | `memory/memory_schema.py` + `memory_store.py` |
| 新增安全规则 | `safety/guardrails.py` |

## 已知注意事项

- `USE_REACT_LOOP = True` 时启用 ReAct 内循环；设为 `False` 回退到 Plan→Execute 模式
- `VERIFY_ON_FINISH = True` 时步骤完成后进行目标验证
- `MAX_STEP_RETRIES = 2`, `MAX_REPLANS = 2`, `MAX_GOAL_EVALUATIONS = 3` — 收敛控制参数在 `workflow.py` 顶部
- 幂等缓存通过 `run_id + step_index + tool + arguments` 键实现，在 `core/idempotency.py` 中管理