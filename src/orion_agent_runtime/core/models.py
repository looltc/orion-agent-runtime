from typing import Any, Callable, Dict, List, Optional, Literal, Type
from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass

# 只放数据结构，不放业务逻辑。


class PlanStep(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
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
    status: Literal["running", "done", "failed"] = "running"
    
    error: Optional[str] = None
    traces: List[ExecutionTrace] = Field(default_factory=list)
    step_retry_count: int = 0
    replan_count: int = 0
    last_decision: Optional[str] = None
    
    knowledge_context: Optional[str] = None


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
