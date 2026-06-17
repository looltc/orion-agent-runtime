from orion_agent_runtime.llm_provider import client, MODEL_NAME

# 答案合成器：根据用户输入和检索到的知识，调用 LLM 生成最终答案。


def _get_text(message) -> str:
    text = message.content or getattr(message, "reasoning_content", None)
    if not text:
        raise ValueError("empty LLM output")
    return text


def synthesize_answer(user_input: str, knowledge_text: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "你是一个知识问答助手。根据给定知识回答问题，不要编造，不要提及检索过程。",
            },
            {
                "role": "user",
                "content": f"""
                    用户问题：
                    {user_input}

                    检索到的知识：
                    {knowledge_text}

                    请基于知识直接回答用户问题，语言简洁清晰。
                    """.strip(),
            },
        ],
    )

    return _get_text(resp.choices[0].message)
