from orion_agent_runtime.knowledge.loader import load_documents

# 知识检索器，负责根据用户查询在加载的知识文档中进行检索，返回最相关的文档内容。

def retrieve(query: str):
    docs = load_documents()
    query = query.lower()
    best_doc = None
    best_score = 0

    for doc in docs:
        score = 0

        for word in query.split():
            if word in doc["content"].lower():
                score += 1

        if score > best_score:
            best_score = score
            best_doc = doc

    return best_doc