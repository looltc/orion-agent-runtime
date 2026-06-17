from pathlib import Path
from orion_agent_runtime.core.skill_loader import get_skill
from orion_agent_runtime.llm_provider import client, MODEL_NAME

# 这个模块负责执行技能


def _get_text(message) -> str:
    text = message.content or getattr(message, "reasoning_content", None)
    if not text:
        raise ValueError("empty LLM output")
    return text


def load_skill_instructions(skill_name: str) -> str:
    spec = get_skill(skill_name)
    skill_dir = Path(spec.path)
    skill_md = skill_dir / "SKILL.md"
    return skill_md.read_text(encoding="utf-8")


def execute_skill(skill_name: str, payload: dict) -> str:
    """
    目录级 Skill 执行器：
    - 找到 skill
    - 读取 SKILL.md
    - 结合 payload 让 LLM 执行技能
    """
    instructions = load_skill_instructions(skill_name)

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "你是一个严格的技能执行器，请遵循给定技能文档，不要发明额外步骤。",
            },
            {
                "role": "user",
                "content": f"""
                    下面是技能说明：

                    {instructions}

                    下面是本次输入 payload：
                    {payload}

                    请直接执行这个技能，并输出最终结果。
                    """.strip(),
            },
        ],
    )

    return _get_text(resp.choices[0].message)
