from orion_agent_runtime.memory.memory_schema import MemoryItem
from orion_agent_runtime.memory.memory_store import MemoryStore

# 记忆层只负责两件事：
# 运行前取记忆
# 运行后写记忆


class MemoryManager:
    def __init__(self):
        self.store = MemoryStore()

    def recall(self, user_id: str):
        return self.store.search_by_user(user_id)

    def recall_related(self, user_id: str, query: str, limit: int = 5):
        return self.store.search_related(user_id=user_id, query=query, limit=limit)

    def remember_task_summary(
        self, user_id: str, summary: str, metadata: dict | None = None
    ):
        item = MemoryItem(
            user_id=user_id,
            kind="task_summary",
            content=summary,
            metadata=metadata or {},
        )
        self.store.add(item)

    def remember_fact(self, user_id: str, fact: str, metadata: dict | None = None):
        item = MemoryItem(
            user_id=user_id,
            kind="fact",
            content=fact,
            metadata=metadata or {},
        )
        self.store.add(item)

    def remember_text(
        self,
        user_id: str,
        kind: str,
        content: str,
        metadata: dict | None = None,
    ):
        item = MemoryItem(
            user_id=user_id,
            kind=kind,
            content=content,
            metadata=metadata or {},
        )
        self.store.add(item)
