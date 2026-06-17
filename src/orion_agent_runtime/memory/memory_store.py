import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from orion_agent_runtime.memory.memory_schema import MemoryItem, MemoryHit

# 存储和检索记忆项。

DB_PATH = Path("./runtime_state/memory.db")


def _tokenize(text: str) -> set[str]:
    """
    混合分词：
    - 英文/数字按词切
    - 中文按单字 + 2-gram
    """
    text = (text or "").lower()
    tokens: set[str] = set()

    # 英文/数字词
    tokens.update(re.findall(r"[a-z0-9_]+", text))

    # 中文块
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        if not chunk:
            continue
        for ch in chunk:
            tokens.add(ch)
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i : i + 2])

    return {t for t in tokens if t}


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.utcnow()


def _kind_weight(kind: str) -> float:
    return {
        "preference": 3.0,
        "fact": 2.5,
        "task_summary": 2.0,
        "tool_result": 1.0,
    }.get(kind, 1.0)


class MemoryStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def add(self, item: MemoryItem) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_items (user_id, kind, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item.user_id,
                    item.kind,
                    item.content,
                    json.dumps(item.metadata, ensure_ascii=False),
                    item.created_at,
                ),
            )

    def search_by_user(self, user_id: str, limit: int = 20) -> List[MemoryItem]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, kind, content, metadata, created_at
                FROM memory_items
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

        items = []
        for user_id, kind, content, metadata, created_at in rows:
            items.append(
                MemoryItem(
                    user_id=user_id,
                    kind=kind,
                    content=content,
                    metadata=json.loads(metadata),
                    created_at=created_at,
                )
            )
        return items

    def search_related(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        kinds: Optional[Sequence[str]] = None,
    ) -> List[MemoryHit]:
        """
        轻量相关性检索：
        score = 关键词重叠 + kind权重 + 近期加分
        """
        candidates = self.search_by_user(user_id=user_id, limit=200)

        if kinds:
            kinds_set = set(kinds)
            candidates = [x for x in candidates if x.kind in kinds_set]

        q_terms = _tokenize(query)
        now = datetime.utcnow()

        scored: List[MemoryHit] = []
        for item in candidates:
            doc_text = (
                item.content + " " + json.dumps(item.metadata, ensure_ascii=False)
            )
            d_terms = _tokenize(doc_text)

            overlap = len(q_terms & d_terms)

            # 近期记忆稍微加分
            age_days = max((now - _parse_dt(item.created_at)).days, 0)
            recency_bonus = 1.0 / (1.0 + age_days)

            score = (overlap * 2.0) + _kind_weight(item.kind) + recency_bonus

            # 没有任何相关词时，也允许按 kind + recency 给一个很弱的兜底分
            if overlap == 0 and item.kind not in {"preference", "fact", "task_summary"}:
                continue

            scored.append(
                MemoryHit(
                    item=item,
                    score=score,
                    reason=f"overlap={overlap}, kind={item.kind}, recency_bonus={recency_bonus:.3f}",
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
