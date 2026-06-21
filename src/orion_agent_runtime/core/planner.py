from orion_agent_runtime.core.skill_loader import build_skill_catalog_text
from orion_agent_runtime.memory.memory import MemoryManager
from orion_agent_runtime.memory.memory_context import format_memories_for_prompt
from orion_agent_runtime.core.models import AgentState, ExecutionTrace, Plan
from orion_agent_runtime.llm_provider import client, MODEL_NAME
from orion_agent_runtime.tools.registry import build_tool_catalog

# 负责让 LM Studio 生成 Plan，然后交给 Pydantic 校验。


skill_catalog = build_skill_catalog_text()
# knowledge_catalog = build_knowledge_catalog_text()
memory_manager = MemoryManager()


def _get_text_from_message(message) -> str:
    text = message.content
    if not text:
        text = getattr(message, "reasoning_content", None)
    if not text:
        raise ValueError("LLM returned empty content")
    return text


def _extract_json_text(raw: str) -> str:
    """
    兜底：如果模型夹了 markdown 或额外文本，截取最外层 JSON。
    """
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no valid JSON found")
    return raw[start : end + 1]


def _call_plan_llm(prompt: str, schema_name: str = "plan") -> Plan:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": Plan.model_json_schema(),
                "strict": True,
            },
        },
        messages=[
            {
                "role": "system",
                "content": "你是一个任务规划器。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    raw = _get_text_from_message(response.choices[0].message)

    # 先直接按 JSON 解析；如果模型夹了多余文本，就截取最外层 JSON
    try:
        return Plan.model_validate_json(raw)
    except Exception:
        return Plan.model_validate_json(_extract_json_text(raw))


def planner(user_input: str, user_id: str) -> Plan:
    tool_catalog = build_tool_catalog()
    related_memories = memory_manager.recall_related(
        user_id=user_id,
        query=user_input,
        limit=5,
    )
    memory_text = format_memories_for_prompt(related_memories)

    prompt = f"""
        可用工具：
        {tool_catalog}
        
        可用技能：
        {skill_catalog}

        用户历史记忆：
        {memory_text}

        当前用户任务：
        {user_input}
        
        首先输出 Loop 收敛所需的两个字段（P1）：
        - goal：用一句话把用户任务目标化重述（可验证的目标，例如"计算 2 与 3 的和"）
        - success_criteria：2-4 条可客观验证的验收标准（例如"输出 5""所有步骤成功执行"）。
          普通问答类也应有验收标准（例如"直接回答了用户问题"）。
        
        然后判断任务类型并输出对应字段：
        
        判断规则：
        1. 普通问答：
        need_tools=false, need_knowledge=false, need_skill=false, direct_answer=直接回答
        
        2. 知识问题：
        need_tools=true, need_knowledge=true, need_skill=false
        steps 中优先使用 knowledge_search
        
        3. 普通原子操作：
        need_tools=true, need_knowledge=false, need_skill=false
        steps 中使用 add / mul / file / search 等工具
        
        4. 高层复合任务：
        need_tools=true, need_knowledge=false, need_skill=true
        skill_name 填对应技能名

        约束规则：
        - 只输出 JSON。
        """.strip()

    return _call_plan_llm(prompt, schema_name="initial_plan")


def replan_from_failure(state: AgentState, failed_trace: ExecutionTrace) -> Plan:
    tool_catalog = build_tool_catalog()
    completed_observations = [o.model_dump() for o in state.observations]
    completed_steps = [s.model_dump() for s in state.plan[: state.current_step]]

    prompt = f"""
        你是一个任务重规划器。
        下面是用户原始任务、已完成步骤、已完成观察、以及失败信息。
        
        可用工具：
        {tool_catalog}

        当前用户任务：
        {state.user_input}

        已完成步骤：
        {completed_steps}

        已完成观察：
        {completed_observations}

        失败的步骤：
        {failed_trace.model_dump()}

        请只输出“剩余步骤”的 JSON 计划，不要重复已完成步骤，不要解释，不要 markdown。

        要求：
        - 只输出 {{"steps": [...]}}
        - 只包含后续需要执行的步骤
        - 如果需要承接上一步结果，使用 null
        - 只使用当前可用工具
        """.strip()

    return _call_plan_llm(prompt, schema_name="replan_plan")


if __name__ == "__main__":
    plan = planner("先算 2 + 3，再乘以 10", user_id="test_user")
    print(plan)
    print(plan.steps[0].tool)
    print(plan.steps[1].tool)
