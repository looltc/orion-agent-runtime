"""Reporter 抽象接口 —— Agent 执行过程可视化。

设计原则：
- 所有 report_* 方法为同步（便于 CLI 即时输出），不返回数据。
- 未来客户端（Web UI / WebSocket / 移动端）只需实现此接口。
- 全局 set_reporter/get_reporter 避免在 workflow/executor/react_loop 间透传参数。
"""

from __future__ import annotations

import abc
import sys
import time
from typing import Any, Optional


class Reporter(abc.ABC):
    """Agent 执行报告器抽象基类。"""

    @abc.abstractmethod
    def task_start(self, user_input: str, run_id: str) -> None: ...

    @abc.abstractmethod
    def plan_generated(self, goal: Optional[str], steps_count: int) -> None: ...

    @abc.abstractmethod
    def tool_call_start(self, tool: str, arguments: dict, step_index: int) -> None: ...

    @abc.abstractmethod
    def tool_call_end(
        self, tool: str, step_index: int, success: bool,
        result: Optional[str], error: Optional[str], elapsed_ms: float,
    ) -> None: ...

    @abc.abstractmethod
    def react_iteration(
        self, iteration: int, thought: str, action: str, tool: Optional[str],
    ) -> None: ...

    @abc.abstractmethod
    def verification(self, achieved: bool, reason: str, iteration: int) -> None: ...

    @abc.abstractmethod
    def task_end(self, status: str, final_output: Optional[str],
                 error: Optional[str]) -> None: ...

    @abc.abstractmethod
    def warn(self, message: str) -> None: ...

    @abc.abstractmethod
    def error(self, message: str) -> None: ...

    @abc.abstractmethod
    def status(self, message: str) -> None: ...


class NoopReporter(Reporter):
    """空 Reporter：什么都不输出（默认）。"""
    def task_start(self, u, r) -> None: pass
    def plan_generated(self, g, n) -> None: pass
    def tool_call_start(self, t, a, i) -> None: pass
    def tool_call_end(self, t, i, s, r, e, ms) -> None: pass
    def react_iteration(self, i, th, a, t) -> None: pass
    def verification(self, a, r, i) -> None: pass
    def task_end(self, s, o, e) -> None: pass
    def warn(self, m) -> None: pass
    def error(self, m) -> None: pass
    def status(self, m) -> None: pass


# ---- 全局访问器 ----

_current: Reporter = NoopReporter()

def set_reporter(r: Reporter) -> None:
    """设置当前 Reporter。由 main.py 调用。"""
    global _current
    _current = r

def get_reporter() -> Reporter:
    """获取当前 Reporter。executor / react_loop / workflow 通过此调用。"""
    return _current


# ---- CLI 实现 ----

class CliReporter(Reporter):
    """CLI 彩色报告器。使用 ANSI 转义码，兼容现代终端。"""

    C = dict(RESET="\033[0m", BOLD="\033[1m", DIM="\033[2m",
             RED="\033[31m", GREEN="\033[32m", YELLOW="\033[33m",
             BLUE="\033[34m", MAGENTA="\033[35m", CYAN="\033[36m")

    def __init__(self):
        self._start_time: float = 0

    def task_start(self, user_input: str, run_id: str) -> None:
        self._start_time = time.time()
        self._line()
        print(f"{self.C['BOLD']}▶ 任务开始{self.C['RESET']} [{run_id}]")
        print(f"  {self.C['DIM']}输入:{self.C['RESET']} {user_input[:120]}")

    def plan_generated(self, goal: Optional[str], steps_count: int) -> None:
        print(f"\n{self.C['BOLD']}📋 计划{self.C['RESET']} ({steps_count}步)")
        if goal:
            print(f"  {self.C['CYAN']}目标:{self.C['RESET']} {goal[:120]}")

    def tool_call_start(self, tool: str, arguments: dict, step_index: int) -> None:
        args = self._fmt(tool, arguments)
        print(f"\n  {self.C['BLUE']}▸{self.C['RESET']} {self.C['YELLOW']}{tool}{self.C['RESET']} {args}")

    def tool_call_end(self, tool, step_index, success, result, error, elapsed_ms):
        icon = f"{self.C['GREEN']}✓{self.C['RESET']}" if success else f"{self.C['RED']}✗{self.C['RESET']}"
        status = "成功" if success else "失败"
        e = f"{elapsed_ms:.0f}ms" if elapsed_ms < 1000 else f"{elapsed_ms/1000:.1f}s"
        s = self._summarize(result) if success else str(error)[:100]
        if s:
            print(f"  {icon} {status} {self.C['DIM']}({e}){self.C['RESET']} {s}")

    def react_iteration(self, iteration: int, thought: str, action: str, tool: Optional[str]):
        label = f"{action}/{tool}" if tool else action
        th = thought[:80] + "..." if len(thought) > 80 else thought
        print(f"  {self.C['MAGENTA']}#{iteration}{self.C['RESET']} {self.C['DIM']}{label}{self.C['RESET']} {th}")

    def verification(self, achieved: bool, reason: str, iteration: int) -> None:
        if achieved:
            print(f"\n{self.C['GREEN']}✅ 目标达成{self.C['RESET']} ({iteration}轮)")
        else:
            print(f"\n{self.C['YELLOW']}🔄 验证未通过{self.C['RESET']} ({iteration}轮): {reason[:100]}")

    def task_end(self, status: str, final_output, error):
        elapsed = time.time() - self._start_time
        s = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
        labels = {"done": f"{self.C['GREEN']}完成{self.C['RESET']}",
                  "goal_achieved": f"{self.C['GREEN']}✅ 目标达成{self.C['RESET']}",
                  "failed": f"{self.C['RED']}✗ 失败{self.C['RESET']}",
                  "paused": f"{self.C['YELLOW']}⏸ 暂停{self.C['RESET']}"}
        print(f"\n{self.C['BOLD']}◀ {labels.get(status, status)}{self.C['RESET']} {self.C['DIM']}({s}){self.C['RESET']}")
        if final_output:
            print(f"\n{self.C['BOLD']}结果{self.C['RESET']}:")
            print(f"  {str(final_output)[:2000]}")
        if error:
            print(f"\n{self.C['RED']}错误:{self.C['RESET']} {error[:500]}")
        self._line()

    def warn(self, message: str) -> None:
        print(f"  {self.C['YELLOW']}⚠{self.C['RESET']} {message}")

    def error(self, message: str) -> None:
        print(f"  {self.C['RED']}✗{self.C['RESET']} {message}")

    def status(self, message: str) -> None:
        print(f"  {self.C['DIM']}⏳{self.C['RESET']} {message}...")

    # ---- helpers ----

    def _fmt(self, tool: str, args: dict) -> str:
        if not args: return ""
        if tool in ("browser_open", "browser_navigate"):
            return str(args.get("url", ""))[:80]
        if tool == "browser_type":
            return f"{self.C['DIM']}{args.get('selector','')}{self.C['RESET']} ← \"{args.get('text','')}\""
        if tool == "browser_click":
            return f"{self.C['DIM']}{args.get('selector','')}{self.C['RESET']}"
        if tool == "browser_press_key":
            return f"\"{args.get('key','')}\""
        if tool == "browser_evaluate_js":
            return str(args.get("script", ""))[:60] + "..."
        s = str(args)
        return s[:100] + "..." if len(s) > 100 else s

    @staticmethod
    def _summarize(result) -> str:
        if not result: return ""
        s = str(result).replace("\n", " ").strip()
        return s[:120] + "..." if len(s) > 120 else s

    @staticmethod
    def _line():
        print(f"{CliReporter.C['DIM']}{'─' * 60}{CliReporter.C['RESET']}")
