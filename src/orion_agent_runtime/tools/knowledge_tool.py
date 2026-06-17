from pydantic import BaseModel
from orion_agent_runtime.knowledge.retriever import retrieve
from orion_agent_runtime.tools.registry import register_tool

# 知识库搜索工具，接受一个查询字符串，返回相关的知识内容。


class KnowledgeArgs(BaseModel):
    query: str


@register_tool("knowledge_search", "知识库搜索", KnowledgeArgs)
def knowledge_search(query: str):
    print(f"Executing knowledge_search with query={query}")

    doc = retrieve(query)

    if not doc:
        return "没有找到相关知识"

    return doc["content"][:2000]
