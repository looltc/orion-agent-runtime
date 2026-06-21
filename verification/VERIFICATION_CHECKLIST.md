# Orion Agent Runtime 改造验收方案

## 一、功能验收

### P0：工程债修复验收
- [ ] **依赖完整性**：`pip install -e .` 成功安装，无依赖冲突
- [ ] **配置外置化**：所有硬编码配置已移至 `config.py`，通过环境变量读取
- [ ] **LLM 工厂化**：`get_llm_client(role="maker"/"checker")` 正常工作
- [ ] **入口点**：`python -m orion_agent_runtime` 或 `orion-runtime` 命令可用

### P1：可验证目标验收
```python
# 测试目标验证功能
from orion_agent_runtime.core.workflow import run_agent
from orion_agent_runtime.core.storage import save_state

state = run_agent("计算 2 + 3", "test_p1", "test_user")
assert state.status == "goal_achieved" or state.status == "done"
assert state.verification is not None  # 验证结果存在
```
- [ ] 目标验证器（Checker）正常调用
- [ ] `VerificationResult` 包含 achieved/reason/evidence/next_action
- [ ] 验证未通过时触发重规划

### P2：ReAct 内循环验收
```python
# 测试 ReAct 模式
from orion_agent_runtime.core.workflow import USE_REACT_LOOP

USE_REACT_LOOP = True
state = run_agent("搜索并总结 AI 最新进展", "test_p2", "test_user")
assert len(state.react_traces) > 0  # 有 ReAct 轨迹
```
- [ ] ReAct 轨迹（thought→action→observation）完整记录
- [ ] 历史压缩功能正常（观察超过 8 条触发压缩）
- [ ] 达到 MAX_ITERATIONS 时正常收尾
- [ ] **回滚验证**：设 `USE_REACT_LOOP = False`，回归 Plan→Execute 模式

### P3：幂等性验收
```python
# 测试幂等缓存
from orion_agent_runtime.core.executor import execute_step
from orion_agent_runtime.core.models import PlanStep
from orion_agent_runtime.tools.registry import get_tool
import orion_agent_runtime.tools  # 注册工具

step = PlanStep(tool="add", arguments={"a": 1, "b": 2})

# 第一次调用
obs1, trace1 = execute_step(step, step_index=1, run_id="test_p3")
call_count_1 = trace1.result  # 假设工具返回调用次数

# 相同参数再次调用
obs2, trace2 = execute_step(step, step_index=1, run_id="test_p3")
call_count_2 = trace2.result

assert call_count_1 == call_count_2  # 命中缓存，真实执行次数不变
```
- [ ] 相同 (run_id, step_index, tool, arguments) 命中缓存
- [ ] 不同 run_id 不命中缓存
- [ ] 缓存统计信息正确

### P4：收敛控制验收
```python
# 测试停滞检测
from orion_agent_runtime.core.stagnation_detector import (
    detect_stagnation,
    mark_stagnation,
)

# 模拟连续相同验证结果
from orion_agent_runtime.core.models import VerificationResult
verification_signatures = ["sig1", "sig1", "sig1", "sig1"]  # 连续 4 次相同

# 测试：检测到停滞
state.stagnation_count = 3  # 已有 3 次停滞
assert detect_stagnation(state, verification_signatures) is True
```
- [ ] 停滞检测在连续 K 次相同验证签名时触发
- [ ] 成本护栏在超预算时终止任务
- [ ] Maker/Checker 角色分离工作正常

### P5：可观测性与安全验收
```python
# 测试审计日志
from orion_agent_runtime.audit.audit_log import log_event, read_events, clear_audit

clear_audit()
log_event("test_p5", "task_start", {"user_input": "test"})
events = read_events("test_p5")
assert len(events) == 1
assert events[0]["event_type"] == "task_start"
```
- [ ] 审计日志正常记录所有关键事件
- [ ] 按 run_id 过滤事件正常
- [ ] 工具调用前后记录审计日志
- [ ] 高风险工具触发批准检查

```python
# 测试安全护栏
from orion_agent_runtime.safety.guardrails import GuardrailConfig, get_guardrails

assert GuardrailConfig.requires_approval("file_write") is True
assert GuardrailConfig.requires_approval("math_add") is False

guardrails = get_guardrails()
result = guardrails.check_before_execution("math_add", {"a": 1, "b": 2}, "test")
assert result.action.value == "approve"
```
- [ ] 风险分级正确（CRITICAL/MEDIUM/LOW）
- [ ] 低风险工具自动批准
- [ ] 高风险工具需要批准（测试时使用 mock 回调）

---

## 二、集成验收

### 端到端任务验收

#### 1. 简单任务（直接回答）
```python
from orion_agent_runtime.core.workflow import run_agent

state = run_agent("什么是量子计算？", "test_e2e_1", "test_user")
assert state.status in ["done", "goal_achieved"]
assert state.final_output is not None
```
**预期结果**：
- ✅ 状态为 `done` 或 `goal_achieved`
- ✅ 有最终输出（直接回答）
- ✅ 审计日志有 `task_start` 和 `task_completed` 事件

#### 2. 工具调用任务
```python
state = run_agent("计算 15 + 27", "test_e2e_2", "test_user")
assert state.status in ["done", "goal_achieved"]
assert "42" in str(state.final_output)
```
**预期结果**：
- ✅ 调用了 `math_add` 工具
- ✅ 结果为 42
- ✅ 审计日志有 `tool_call_start` 和 `tool_call_success` 事件
- ✅ ReAct 模式下有 `react_decision` 事件

#### 3. 多步骤任务
```python
state = run_agent(
    "先计算 10 + 20，然后将结果乘以 3",
    "test_e2e_3",
    "test_user",
)
assert state.status in ["done", "goal_achieved"]
# 10 + 20 = 30, 30 * 3 = 90
assert "90" in str(state.final_output)
```
**预期结果**：
- ✅ 执行了多个工具调用
- ✅ ReAct 模式下有多条 `react_decision` 轨迹
- ✅ 历史压缩在观察过多时触发

#### 4. 失败重试任务
```python
# 测试工具失败后的重试机制
state = run_agent("故意调用不存在的工具测试错误处理", "test_e2e_4", "test_user")
# 应该优雅降级，而非崩溃
assert state.status in ["done", "failed"]
```
**预期结果**：
- ✅ 不会崩溃
- ✅ 错误信息记录在 `state.error` 中
- ✅ 审计日志有 `tool_call_failed` 事件

---

## 三、回滚验收

### 验证回滚开关有效性

```python
# 1. 关闭 ReAct 内循环
from orion_agent_runtime.core import workflow
workflow.USE_REACT_LOOP = False

state = run_agent("测试 Plan→Execute 模式", "test_rollback_1", "test_user")
assert len(state.react_traces) == 0  # 没有 ReAct 轨迹
assert len(state.traces) > 0  # 有 ExecutionTrace

# 2. 关闭目标验证
workflow.VERIFY_ON_FINISH = False

state = run_agent("测试不验证模式", "test_rollback_2", "test_user")
assert state.status == "done"  # 直接 done，不经过 verification
```
**验收标准**：
- ✅ `USE_REACT_LOOP = False` 时回归 Plan→Execute 模式
- ✅ `VERIFY_ON_FINISH = False` 时跳过目标验证
- ✅ 所有功能关闭后系统仍可正常运行

---

## 四、性能验收

### 关键指标

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| 工具调用延迟 | < 500ms | 记录 execute_step 执行时间 |
| 幂等缓存命中率 | > 80% | 同任务重试时检查缓存命中 |
| ReAct 循环平均迭代次数 | < 5 | 分析 react_traces 长度 |
| 审计日志写入延迟 | < 10ms | 记录 log_event 执行时间 |
| 状态恢复时间 | < 1s | 模拟崩溃后从磁盘恢复 |

```python
import time

# 性能测试示例
start = time.time()
from orion_agent_runtime.core.executor import execute_step
# ... 执行工具调用 ...
duration = time.time() - start
print(f"工具调用耗时: {duration * 1000:.2f}ms")
```

---

## 五、安全验收

### 安全护栏测试

```python
# 1. 高风险工具必须批准
from orion_agent_runtime.safety.guardrails import GuardrailConfig

high_risk_tools = [
    "file_write", "file_delete", "execute_command",
    "database_write", "database_delete", "api_post", "api_delete"
]

for tool in high_risk_tools:
    assert GuardrailConfig.requires_approval(tool), f"{tool} 应需要批准"

# 2. 低风险工具自动批准
low_risk_tools = ["math_add", "text_search", "knowledge_search"]

for tool in low_risk_tools:
    assert not GuardrailConfig.requires_approval(tool), f"{tool} 不应需要批准"
```

### 审计日志完整性

```python
# 验证所有关键事件都被记录
from orion_agent_runtime.audit.audit_log import read_events
from orion_agent_runtime.core.workflow import run_agent

state = run_agent("审计日志完整性测试", "test_security", "test_user")
events = read_events("test_security")

event_types = [e["event_type"] for e in events]
required_events = ["task_start", "task_completed"]

for req_event in required_events:
    assert req_event in event_types, f"缺少必需事件: {req_event}"
```

---

## 六、测试套件验收

### 运行所有测试

```bash
# 进入项目目录
cd D:\AIWorkspace\orion-agent-runtime

# 运行核心测试（需要 pytest）
python -m pytest tests/test_core.py -v

# 运行幂等性测试
python -m pytest tests/test_idempotency.py -v

# 运行目标验证测试
python -m pytest tests/test_goal_verification.py -v

# 运行 ReAct 循环测试
python -m pytest tests/test_react_loop.py -v

# 运行收敛控制测试
python -m pytest tests/test_convergence_control.py -v

# 运行安全护栏测试
python -m pytest tests/test_guardrails.py -v

# 运行审计日志测试
python -m pytest tests/test_audit_log.py -v

# 运行所有测试
python -m pytest tests/ -v
```

**验收标准**：
- ✅ 所有测试通过（或明确标记为 skip/xfail）
- ✅ 无意外的测试失败
- ✅ 测试覆盖率 > 80%（可选）

---

## 七、文档验收

- [ ] **架构文档**：说明 Loop Engineering 设计
- [ ] **API 文档**：主要模块和函数的 docstring 完整
- [ ] **配置文档**：环境变量说明完整
- [ ] **部署文档**：安装和运行说明清晰
- [ ] **开发文档**：如何添加新工具、如何扩展功能

---

## 八、验收报告模板

```markdown
# Orion Agent Runtime 改造验收报告

**验收日期**：2026-06-21
**验收人**：__________
**环境**：Windows 10 + Python 3.12

## 功能验收结果

| 模块 | 状态 | 备注 |
|------|------|------|
| P0: 工程债修复 | ✅ 通过 | 所有依赖正常，配置外置化完成 |
| P1: 可验证目标 | ⬜ 待验收 | ______ |
| P2: ReAct 内循环 | ⬜ 待验收 | ______ |
| P3: 幂等性 | ⬜ 待验收 | ______ |
| P4: 收敛控制 | ⬜ 待验收 | ______ |
| P5: 可观测性+安全 | ⬜ 待验收 | ______ |

## 集成验收结果

| 测试场景 | 状态 | 备注 |
|---------|------|------|
| 简单任务 | ⬜ 待验收 | ______ |
| 工具调用任务 | ⬜ 待验收 | ______ |
| 多步骤任务 | ⬜ 待验收 | ______ |
| 失败重试任务 | ⬜ 待验收 | ______ |

## 回滚验收结果

| 开关 | 状态 | 备注 |
|------|------|------|
| USE_REACT_LOOP = False | ⬜ 待验收 | ______ |
| VERIFY_ON_FINISH = False | ⬜ 待验收 | ______ |

## 性能验收结果

| 指标 | 实测值 | 目标值 | 状态 |
|------|--------|--------|------|
| 工具调用延迟 | ______ ms | < 500ms | ⬜ 待验收 |
| 幂等缓存命中率 | ______ % | > 80% | ⬜ 待验收 |

## 安全验收结果

| 检查项 | 状态 | 备注 |
|--------|------|------|
| 高风险工具批准 | ⬜ 待验收 | ______ |
| 审计日志完整性 | ⬜ 待验收 | ______ |

## 测试套件验收结果

- 测试文件数：______
- 测试用例数：______
- 通过：______
- 失败：______
- 跳过：______

**总体评价**：⬜ 通过 / ⬜ 有条件通过 / ⬜ 不通过

**问题与建议**：
1. ______
2. ______
3. ______

**验收人签字**：__________
```

---

## 快速验收脚本

创建 `verify.py` 快速验收脚本：

```python
#!/usr/bin/env python3
"""快速验收脚本 - 验证核心功能"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """测试所有模块可以正常导入"""
    try:
        from orion_agent_runtime.config import get_config
        from orion_agent_runtime.llm_provider import get_llm_client
        from orion_agent_runtime.core.workflow import run_agent
        from orion_agent_runtime.core.executor import execute_step
        from orion_agent_runtime.core.goal_evaluator import evaluate_goal
        from orion_agent_runtime.core.react_loop import run_react_loop
        from orion_agent_runtime.core.idempotency import get_cache
        from orion_agent_runtime.core.stagnation_detector import detect_stagnation
        from orion_agent_runtime.core.cost_guardrail import budget_exceeded
        from orion_agent_runtime.trace.metrics_collector import collect_metrics
        from orion_agent_runtime.audit.audit_log import log_event, read_events
        from orion_agent_runtime.safety.guardrails import GuardrailConfig, get_guardrails
        print("✅ 所有模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 模块导入失败: {e}")
        return False

def test_config():
    """测试配置加载"""
    try:
        from orion_agent_runtime.config import get_config
        config = get_config()
        print(f"✅ 配置加载成功: runtime_state_dir={config.runtime_state_dir}")
        return True
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return False

def test_audit_log():
    """测试审计日志"""
    try:
        from orion_agent_runtime.audit.audit_log import log_event, read_events, clear_audit
        clear_audit()
        log_event("verify_test", "test_event", {"data": 123})
        events = read_events("verify_test")
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"
        print("✅ 审计日志正常工作")
        return True
    except Exception as e:
        print(f"❌ 审计日志测试失败: {e}")
        return False

def test_guardrails():
    """测试安全护栏"""
    try:
        from orion_agent_runtime.safety.guardrails import GuardrailConfig, get_guardrails
        assert GuardrailConfig.requires_approval("file_write")
        assert not GuardrailConfig.requires_approval("math_add")
        guardrails = get_guardrails()
        result = guardrails.check_before_execution("math_add", {"a": 1}, "test")
        assert result.action.value == "approve"
        print("✅ 安全护栏正常工作")
        return True
    except Exception as e:
        print(f"❌ 安全护栏测试失败: {e}")
        return False

def main():
    print("="*60)
    print("Orion Agent Runtime 快速验收")
    print("="*60)

    tests = [
        ("模块导入", test_imports),
        ("配置加载", test_config),
        ("审计日志", test_audit_log),
        ("安全护栏", test_guardrails),
    ]

    results = []
    for name, test_func in tests:
        print(f"\n[{name}]")
        result = test_func()
        results.append((name, result))

    print("\n" + "="*60)
    print("验收结果汇总")
    print("="*60)
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)
    print("="*60)
    if all_passed:
        print("🎉 所有快速验收项目通过！")
        return 0
    else:
        print("⚠️  部分验收项目未通过，请检查详细日志")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

**使用方法**：
```bash
cd D:\AIWorkspace\orion-agent-runtime
python verify.py
```

---

## 总结

按此验收方案进行验证，确保：

1. **功能完整性**：P0-P5 所有功能按预期工作
2. **集成正确性**：各模块协同工作无异常
3. **回滚可靠性**：回滚开关有效，可随时退回旧模式
4. **性能达标**：关键指标满足要求
5. **安全保障**：安全护栏和审计日志正常工作
6. **测试覆盖**：测试套件充分且通过

验收通过后，系统即可投入生产使用！