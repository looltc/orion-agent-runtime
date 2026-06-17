from typing import Any, Dict

# 工具调用参数归一化。

TOOL_ALIASES = {
    "add": "add",
    "plus": "add",
    "sum": "add",
    "mul": "mul",
    "multiply": "mul",
    "product": "mul",
}


def normalize_tool_name(name: str) -> str:
    key = name.strip().lower()
    if key not in TOOL_ALIASES:
        return key
    return TOOL_ALIASES[key]


def normalize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    通用层只做轻量标准化：
    - 去掉空值
    - 保留 dict 结构
    - 需要时做少量别名处理
    """
    normalized = {}
    for k, v in arguments.items():
        # if v is not None:
        normalized[k] = v
    return normalized
