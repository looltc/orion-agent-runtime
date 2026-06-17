# benchmark/intent_router.py
from orion_agent_runtime.core.models import Plan

# 根据 Plan 的内容推断应该走哪条执行路径：普通问答、工具调用、知识检索、技能执行等。


def infer_route(plan: Plan) -> str:
    if not plan.need_tools and not plan.need_knowledge and not plan.need_skill:
        return "chat"
    if plan.need_skill:
        return "skill"
    if plan.need_knowledge:
        return "knowledge"
    return "tool"


def infer_primary_tool(plan: Plan) -> str | None:
    if not plan.steps:
        return None
    return plan.steps[0].tool


def infer_primary_source(plan: Plan) -> str | None:
    if not plan.steps:
        return None
    step = plan.steps[0]
    return step.arguments.get("source")


def infer_primary_skill(plan: Plan) -> str | None:
    return plan.skill_name
