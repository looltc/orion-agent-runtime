from pydantic import BaseModel, Field
from orion_agent_runtime.tools.registry import register_tool

# 这里放一些简单的数学工具，供测试和示例用。


class AddArgs(BaseModel):
    a: int = Field(..., description="左操作数")
    b: int = Field(..., description="右操作数")


class MulArgs(BaseModel):
    a: int = Field(..., description="左操作数")
    b: int = Field(..., description="右操作数")


@register_tool("add", "计算加法", AddArgs)
def add(a: int, b: int) -> int:
    print(f"Executing add with a={a}, b={b}")
    return a + b


@register_tool("mul", "计算乘法", MulArgs)
def mul(a: int, b: int) -> int:
    print(f"Executing mul with a={a}, b={b}")
    return a * b
