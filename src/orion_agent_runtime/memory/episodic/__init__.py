"""Episodic memory 子包（事件经历，按 run/时间组织，持久化）。

设计文档第 4 节 memory 模块：Episodic 记录"发生过的事件经历"。
对应 V1 中 kind="task_summary" 的扁平字符串，V2 升级为结构化 episode：
  run_id + 步骤序列 + 起止时间 + 成败 + 摘要。
"""

from orion_agent_runtime.memory.episodic.episodic_store import EpisodicStore

__all__ = ["EpisodicStore"]
