# benchmark/intent_report.py
from orion_agent_runtime.benchmark.case002.intent_runner import run_all_intent_cases

# 生成意图路由评估报告


def generate_intent_report(results):
    total = len(results)
    success_count = sum(1 for r in results if r.success)
    success_rate = success_count / total if total else 0.0

    print("=" * 60)
    print(f"Intent Routing Success Rate: {success_rate:.2%}")
    print("=" * 60)

    for r in results:
        print(
            f"{r.case_name}: "
            f"{'PASS' if r.success else 'FAIL'} | "
            f"expected={r.expected_route} actual={r.actual_route}"
        )
        if not r.success:
            print(f"  tool: expected={r.expected_tool}, actual={r.actual_tool}")
            print(f"  skill: expected={r.expected_skill}, actual={r.actual_skill}")
            print(f"  source: expected={r.expected_source}, actual={r.actual_source}")
            if r.error:
                print(f"  error: {r.error}")


if __name__ == "__main__":
    results = run_all_intent_cases()
    generate_intent_report(results)
