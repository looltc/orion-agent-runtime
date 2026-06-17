from pydantic import BaseModel

# 基准测试评估结果

class EvalResult(BaseModel):
    case_name: str
    success: bool
    score: float
    expected: str
    actual: str
    error: str | None = None