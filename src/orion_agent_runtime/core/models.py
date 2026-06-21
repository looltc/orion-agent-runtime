from typing import Any, Callable, Dict, List, Optional, Literal, Type
from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass

# 只放数据结构，不放业务逻辑。


class PlanStep(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ReactAction(BaseModel):
    """ReAct 内循环中 LLM 的单步决策（P2）。

    type:
    - "call_tool"：调用一个工具，观察结果后进入下一轮推理
    - "finish"  ：任务完成，answer 即最终输出
    """

    thought: str = ""
    type: Literal["call_tool", "finish"]
    tool: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    answer: Optional[str] = None


class ReactTrace(BaseModel):
    """ReAct 单轮轨迹，与 ExecutionTrace 并存以便复盘 thought→action→observation。"""

    iteration: int
    thought: str = ""
    action_type: str
    tool: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    observation: Optional[Any] = None
    answer: Optional[str] = None


class Plan(BaseModel):
    # Loop Engineering 核心：可验证目标 + 验收标准（P1）
    # goal 是用户任务的目标化重述，success_criteria 是可验证的验收点。
    goal: str = ""
    success_criteria: List[str] = Field(default_factory=list)

    need_tools: bool
    need_knowledge: bool
    need_skill: bool
    skill_name: str
    direct_answer: str
    steps: List[PlanStep]


class Observation(BaseModel):
    step: int
    tool: str
    result: Any


class VerificationResult(BaseModel):
    """goal_evaluator（Checker）的结构化输出。

    next_action:
    - "finish"  : 验收通过，任务完成
    - "continue": 未通过但可继续 ReAct 迭代（P2）/ 重规划（P1 复用 replan 路径）
    - "refine"  : 需要细化策略（P4 停滞检测会用到）
    """

    achieved: bool
    reason: str = ""
    evidence: str = ""
    next_action: Literal["finish", "continue", "refine"] = "continue"


class ExecutionTrace(BaseModel):
    step_index: int
    raw_tool: str
    normalized_tool: Optional[str] = None
    raw_arguments: Dict[str, Any] = Field(default_factory=dict)
    normalized_arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    success: bool = False
    error: Optional[str] = None


class AgentState(BaseModel):
    run_id: str
    user_input: str
    plan: List[PlanStep] = Field(default_factory=list)
    current_step: int = 0
    observations: List[Observation] = Field(default_factory=list)
    previous_result: Optional[Any] = None
    final_output: Optional[Any] = None
    # done 仅表示"步骤跑完"；goal_achieved 才表示"目标被 checker 验证达成"（P1）
    status: Literal["running", "done", "failed", "goal_achieved", "paused"] = "running"

    error: Optional[str] = None
    traces: List[ExecutionTrace] = Field(default_factory=list)
    step_retry_count: int = 0
    replan_count: int = 0
    last_decision: Optional[str] = None

    knowledge_context: Optional[str] = None

    # ---- P1: Loop 收敛相关字段 ----
    goal: str = ""
    success_criteria: List[str] = Field(default_factory=list)
    iterations: int = 0
    verification: Optional[VerificationResult] = None

    # ---- P2: ReAct 内循环相关字段 ----
    react_traces: List[ReactTrace] = Field(default_factory=list)
    # 历史压缩后的摘要（观察序列过长时写入，避免上下文爆炸）
    history_summary: Optional[str] = None

    # ---- P4: 收敛控制相关字段 ----
    # 连续无新进展的验证轮数；超过阈值时触发暂停（停滞检测）
    stagnation_count: int = 0
    # 累计 token 估算与成本（P4 成本护栏）
    total_tokens: int = 0
    cost_estimate: float = 0.0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    origin: str  # "local" or "mcp"
    args_model: Optional[Type[BaseModel]] = None
    handler: Optional[Callable[..., Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    server_name: Optional[str] = None
    remote_name: Optional[str] = None
