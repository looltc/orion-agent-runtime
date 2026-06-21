import argparse
import json
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from orion_agent_runtime.core.storage import load_state, STATE_DIR
from orion_agent_runtime.trace.metrics_collector import collect_metrics, format_metrics
from orion_agent_runtime.trace.trace_inspector import inspect_trace, format_report

# 运行时数据检查工具，提供命令行接口查看和导出 Agent 运行时的状态和调用轨迹。


class ObservationReport(BaseModel):
    step: int
    tool: str
    result: Any


class TraceReportItem(BaseModel):
    step_index: int
    raw_tool: str
    normalized_tool: Optional[str] = None
    raw_arguments: dict = Field(default_factory=dict)
    normalized_arguments: dict = Field(default_factory=dict)
    result: Optional[Any] = None
    success: bool = False
    error: Optional[str] = None


class RunReport(BaseModel):
    run_id: str
    status: str
    current_step: int
    plan_len: int
    observations_len: int
    traces_len: int
    previous_result: Optional[Any] = None
    final_output: Optional[Any] = None
    error: Optional[str] = None
    trace_report: dict = Field(default_factory=dict)
    plan: list = Field(default_factory=list)
    observations: list = Field(default_factory=list)
    traces: list = Field(default_factory=list)


def _dump_any(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_dump_any(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump_any(v) for k, v in obj.items()}
    return obj


def build_run_report(run_id: str) -> Optional[RunReport]:
    state = load_state(run_id)
    if state is None:
        return None

    trace_report = inspect_trace(state)

    return RunReport(
        run_id=state.run_id,
        status=state.status,
        current_step=state.current_step,
        plan_len=len(state.plan),
        observations_len=len(state.observations),
        traces_len=len(state.traces),
        previous_result=_dump_any(state.previous_result),
        final_output=_dump_any(state.final_output),
        error=state.error,
        trace_report=(
            trace_report.model_dump()
            if hasattr(trace_report, "model_dump")
            else dict(trace_report)
        ),
        plan=[_dump_any(x) for x in state.plan],
        observations=[_dump_any(x) for x in state.observations],
        traces=[_dump_any(x) for x in state.traces],
    )


def _pretty(obj) -> str:
    if obj is None:
        return "None"
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), ensure_ascii=False, indent=2)
    if isinstance(obj, list):
        return json.dumps(
            [x.model_dump() if hasattr(x, "model_dump") else x for x in obj],
            ensure_ascii=False,
            indent=2,
        )
    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return str(obj)


def list_runs() -> None:
    print(f"State dir: {STATE_DIR.resolve()}")
    files = sorted(Path(STATE_DIR).glob("*.json"))
    if not files:
        print("No runs found.")
        return

    for f in files:
        print(f.stem)


def inspect_run(run_id: str, show_full: bool = False) -> None:
    state = load_state(run_id)
    if state is None:
        print(f"[not found] run_id={run_id}")
        return

    print("=" * 80)
    print(f"run_id: {state.run_id}")
    print(f"status: {state.status}")
    print(f"current_step: {state.current_step}")
    print(f"plan_len: {len(state.plan)}")
    print(f"observations_len: {len(state.observations)}")
    print(f"traces_len: {len(state.traces)}")
    print(f"previous_result: {state.previous_result}")
    print(f"final_output: {state.final_output}")
    print(f"error: {state.error}")
    print("=" * 80)

    # P5：运行指标（迭代数、成功率、token 消耗、收敛情况）
    print("METRICS")
    print("-" * 80)
    print(format_metrics(collect_metrics(state)))
    print("-" * 80)

    report = inspect_trace(state)
    print("TRACE REPORT")
    print("-" * 80)
    print(format_report(report))
    print("-" * 80)

    print("PLAN")
    print("-" * 80)
    for i, step in enumerate(state.plan, start=1):
        print(f"[{i}] tool={step.tool}")
        print(_pretty(step.arguments))

    print("-" * 80)
    print("OBSERVATIONS")
    print("-" * 80)
    for obs in state.observations:
        print(f"[step {obs.step}] tool={obs.tool} result={obs.result}")

    print("-" * 80)
    print("TRACES")
    print("-" * 80)
    for tr in state.traces:
        print(
            f"[step {tr.step_index}] "
            f"raw_tool={tr.raw_tool} "
            f"normalized_tool={tr.normalized_tool} "
            f"success={tr.success}"
        )
        if tr.error:
            print(f"  error: {tr.error}")
        if show_full:
            print("  raw_arguments:", _pretty(tr.raw_arguments))
            print("  normalized_arguments:", _pretty(tr.normalized_arguments))
            print("  result:", tr.result)

    # P5：ReAct 轨迹（thought→action→observation）
    if state.react_traces:
        print("-" * 80)
        print("REACT TRACES")
        print("-" * 80)
        for rt in state.react_traces:
            print(f"[iter {rt.iteration}] action={rt.action_type} tool={rt.tool}")
            if rt.thought:
                print(f"  thought: {rt.thought}")
            print(f"  args: {rt.arguments}")
            print(f"  observation: {rt.observation}")
            if rt.answer:
                print(f"  answer: {rt.answer}")

    print("=" * 80)


def export_run_json(run_id: str, output_path: str) -> None:
    report = build_run_report(run_id)
    if report is None:
        raise FileNotFoundError(f"run not found: {run_id}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)

    print(f"exported to: {path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Inspect a saved Agent runtime run.")
    parser.add_argument("--run-id", type=str, help="run id to inspect")
    parser.add_argument("--list", action="store_true", help="list saved runs")
    parser.add_argument("--full", action="store_true", help="show full trace details")
    parser.add_argument("--json", action="store_true", help="print report as JSON")
    parser.add_argument(
        "--out", type=str, default=None, help="export report to json file"
    )
    args = parser.parse_args()

    if args.list:
        list_runs()
        return

    if not args.run_id:
        parser.error("--run-id is required unless --list is used")

    report = build_run_report(args.run_id)
    if report is None:
        print(f"[not found] run_id={args.run_id}")
        return

    if args.out:
        export_run_json(args.run_id, args.out)
        return

    if args.json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
        return

    inspect_run(args.run_id, show_full=args.full)


if __name__ == "__main__":
    main()
