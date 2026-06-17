from pydantic import BaseModel
from typing import Literal

# 设计一些输入，测试 planner 能否正确规划出预期的路线、工具、技能等


class IntentCase(BaseModel):
    name: str
    input: str
    expected_route: Literal["chat", "tool", "knowledge", "skill"]
    expected_tool: str | None = None
    expected_skill: str | None = None
    expected_source: str | None = None


CASES = [
    IntentCase(
        name="chat_001",
        input="你是谁",
        expected_route="chat",
    ),
    IntentCase(
        name="tool_001",
        input="2+3",
        expected_route="tool",
        expected_tool="add",
    ),
    IntentCase(
        name="tool_002",
        input="2+3然后乘10",
        expected_route="tool",
        expected_tool="add",
    ),
    IntentCase(
        name="knowledge_001",
        input="公司请假制度是什么",
        expected_route="knowledge",
        expected_tool="knowledge_search",
    ),
    IntentCase(
        name="skill_001",
        input="帮我总结这段会议内容",
        expected_route="skill",
        expected_skill="summarize-meeting",
    ),
]
