from orion_agent_runtime.benchmark.case001.runner import run_all

# 基准测试报告生成

def generate_report(results):

    total = len(results)

    success_count = sum(1 for r in results if r.success)

    success_rate = success_count / total if total else 0

    print("=" * 60)

    print(f"Success Rate: {success_rate:.2%}")

    print("=" * 60)

    for r in results:
        print(f"{r.case_name}: " f"{'PASS' if r.success else 'FAIL'}")


if __name__ == "__main__":
    results = run_all()
    generate_report(results)
