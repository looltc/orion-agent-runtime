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