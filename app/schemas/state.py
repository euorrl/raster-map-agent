import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """合并 LangGraph 节点返回的动态字典分区。"""

    merged = dict(left)
    for key, value in right.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged


class AgentState(BaseModel):
    """栅格地图 Agent workflow 中流转的共享状态。"""

    user_query: str

    plan: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    workspace: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    tool_results: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    metadata: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)

    final_answer: str | None = None

    status: str = "initialized"
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
    warnings: Annotated[list[str], operator.add] = Field(default_factory=list)
