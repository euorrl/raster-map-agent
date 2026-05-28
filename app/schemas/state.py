import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """递归合并 LangGraph 节点返回的动态字典分区。

    LangGraph 中多个节点可能会先后返回同一个 state 分区的局部更新。
    例如一个节点写入 ``tool_results["raster_prepare"]``，另一个节点写入
    ``tool_results["render_preview"]``。如果直接覆盖，前一个结果会丢失；
    使用这个 reducer 后，新的 key 会被追加，已有 key 会被更新。

    当左右两侧同一个 key 的值都是 dict 时，会继续递归合并；否则右侧
    的新值覆盖左侧旧值。
    """

    merged = dict(left)
    for key, value in right.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged


class AgentState(BaseModel):
    """栅格地图 Agent workflow 中流转的共享状态。

    这个 state 是 LangGraph 节点之间唯一共享的上下文。节点不直接互相
    调用，也不通过全局变量传递数据，而是读取当前 state，并返回一小段
    state 更新。

    字段分区说明：
        user_query: 用户原始输入，不通过 reducer 合并。
        plan: Agent 对任务的结构化计划，例如指数类型、AOI、时间范围、
            数据源、输出偏好和可调整参数。
        tool_calls: 系统根据 plan 编译出的工具调用计划，后续由 executor 执行。
        workspace: 当前任务的工作区信息，例如 run_id 和 workspace_dir。
        tool_results: 各工具的运行结果，按工具名分区保存，例如
            raster_prepare、index_calculation、render_preview。
        metadata: 面向最终记录和导出的元数据，可由多个节点逐步补充。
        runtime: workflow 运行时控制信息，例如 retry 次数、当前阶段、
            validator 结果和局部 ReAct 状态。它不是最终产物 metadata。
        final_answer: 最终返回给用户的文本答案。
        status: 当前 workflow 状态，例如 initialized、planned、failed、
            completed。
        errors: 可追加的错误列表，适合记录历史失败原因。
        warnings: 可追加的警告列表，适合记录非阻塞问题。
    """

    user_query: str

    plan: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    workspace: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    tool_results: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    metadata: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)
    runtime: Annotated[dict[str, Any], merge_dicts] = Field(default_factory=dict)

    final_answer: str | None = None

    status: str = "initialized"
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
    warnings: Annotated[list[str], operator.add] = Field(default_factory=list)
