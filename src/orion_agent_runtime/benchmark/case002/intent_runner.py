# benchmark/intent_runner.py
from orion_agent_runtime.benchmark.case002.intent_dataset import CASES, IntentCase
from orion_agent_runtime.benchmark.case002.intent_evaluator import IntentEvalResult
from orion_agent_runtime.benchmark.case002.intent_router import (
    infer_route,
    infer_primary_tool,
    infer_primary_skill,
    infer_primary_source,
)
from orion_agent_runtime.core.planner import planner

# 运行单个意图测试用例


def run_intent_case(case: IntentCase, user_id: str = "benchmark") -> IntentEvalResult:
    try:
        plan = planner(user_input=case.input, user_id=user_id)

        actual_route = infer_route(plan)
        actual_tool = infer_primary_tool(plan)
        actual_skill = infer_primary_skill(plan)
        actual_source = infer_primary_source(plan)

        success = True

        if actual_route != case.expected_route:
            success = False

        if case.expected_tool and actual_tool != case.expected_tool:
            success = False

        if case.expected_skill and actual_skill != case.expected_skill:
            success = False

        if case.expected_source and actual_source != case.expected_source:
            success = False

        return IntentEvalResult(
            case_name=case.name,
            success=success,
            expected_route=case.expected_route,
            actual_route=actual_route,
            expected_tool=case.expected_tool,
            actual_tool=actual_tool,
            expected_skill=case.expected_skill,
            actual_skill=actual_skill,
            expected_source=case.expected_source,
            actual_source=actual_source,
        )

    except Exception as e:
        return IntentEvalResult(
            case_name=case.name,
            success=False,
            expected_route=case.expected_route,
            actual_route="error",
            expected_tool=case.expected_tool,
            expected_skill=case.expected_skill,
            expected_source=case.expected_source,
            error=str(e),
        )


def run_all_intent_cases():
    results = []
    for case in CASES:
        results.append(run_intent_case(case))
    return results
