# benchmark/intent_evaluator.py
from pydantic import BaseModel
from typing import Optional

# 定义评估结果的数据模型

class IntentEvalResult(BaseModel):
    case_name: str
    success: bool
    expected_route: str
    actual_route: str
    expected_tool: Optional[str] = None
    actual_tool: Optional[str] = None
    expected_skill: Optional[str] = None
    actual_skill: Optional[str] = None
    expected_source: Optional[str] = None
    actual_source: Optional[str] = None
    error: Optional[str] = None