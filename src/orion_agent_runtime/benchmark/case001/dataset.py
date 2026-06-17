from pydantic import BaseModel

# 基准测试数据集


class BenchmarkCase(BaseModel):
    name: str
    input: str
    expected: str


CASES = [
    BenchmarkCase(name="chat_001", input="你是谁", expected="chat"),
    BenchmarkCase(name="math_001", input="2+3", expected="5"),
    BenchmarkCase(name="workflow_001", input="2+3然后乘10", expected="50"),
]
