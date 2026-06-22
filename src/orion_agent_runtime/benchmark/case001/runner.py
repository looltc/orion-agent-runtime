from orion_agent_runtime.benchmark.case001.dataset import CASES
from orion_agent_runtime.benchmark.case001.evaluator import EvalResult
from orion_agent_runtime.core.workflow import run_agent
import uuid

# 基准测试执行器


def run_case(case):

    run_id = str(uuid.uuid4())[:8]

    try:

        state = run_agent(user_input=case.input, user_id="benchmark", run_id=run_id)

        actual = str(state.final_output)

        success = state.status == "goal_achieved"
        if case.name.startswith("chat_"):
            # 对于聊天类用例，根据status来判断是否成功
            success = state.status == "goal_achieved"

        return EvalResult(
            case_name=case.name,
            success=success,
            score=1.0 if success else 0.0,
            expected=case.expected,
            actual=actual,
        )

    except Exception as e:

        return EvalResult(
            case_name=case.name,
            success=False,
            score=0,
            expected=case.expected,
            actual="",
            error=str(e),
        )


def run_all():
    results = []

    for case in CASES:
        result = run_case(case)
        results.append(result)

    return results
