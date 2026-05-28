from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agent.adjusters import (
    adjust_raster_prepare_tool_call,
    build_raster_prepare_adjustment_update,
)
from app.agent.validators import (
    build_raster_prepare_validation_update,
    validate_raster_prepare_result,
)
from app.schemas import AgentState

ValidatorFn = Callable[[AgentState], Any]
ValidationUpdateBuilder = Callable[[Any], dict[str, Any]]
AdjusterFn = Callable[..., Any]
AdjustmentUpdateBuilder = Callable[[AgentState, Any], dict[str, Any]]


@dataclass(frozen=True)
class ToolRule:
    """工具执行后的 workflow 规则。

    ToolRule 不负责执行工具本身。它绑定 compiler 生成的 tool call 短 id，
    声明对应工具结果是否需要验证、可重试失败是否允许进入 adjuster，以及最多
    允许重试多少次。
    """

    tool_call_id: str
    validator: ValidatorFn
    validation_update_builder: ValidationUpdateBuilder
    adjuster: AdjusterFn
    adjustment_update_builder: AdjustmentUpdateBuilder
    max_retries: int = 5
    retryable_status: str = "retryable"


TOOL_RULES_BY_CALL_ID: dict[str, ToolRule] = {
    "raster_prepare": ToolRule(
        tool_call_id="raster_prepare",
        validator=validate_raster_prepare_result,
        validation_update_builder=build_raster_prepare_validation_update,
        adjuster=adjust_raster_prepare_tool_call,
        adjustment_update_builder=build_raster_prepare_adjustment_update,
        max_retries=5,
    )
}


def get_tool_rule(tool_call_id: str) -> ToolRule:
    """返回指定 tool call 短 id 对应的后处理规则。"""

    try:
        return TOOL_RULES_BY_CALL_ID[tool_call_id]
    except KeyError as error:
        raise ValueError(f"Unsupported tool rule: {tool_call_id}") from error


def get_tool_retry_count(state: AgentState, tool_call_id: str) -> int:
    """返回某个 tool call 当前已经重试的次数。"""

    retry_counts = state.runtime.get("retry_counts", {})
    return int(retry_counts.get(tool_call_id, 0))


def can_retry_tool(state: AgentState, tool_call_id: str) -> bool:
    """判断某个 tool call 是否还能进入 adjust-and-retry 流程。"""

    rule = get_tool_rule(tool_call_id)
    validators = state.runtime.get("validators", {})
    validation = validators.get(tool_call_id, {})
    if not isinstance(validation, dict):
        return False
    if validation.get("status") != rule.retryable_status:
        return False

    return get_tool_retry_count(state, tool_call_id) < rule.max_retries


def build_retry_exhausted_update(
    state: AgentState,
    tool_call_id: str,
) -> dict[str, Any]:
    """构造工具重试次数耗尽时的 state 更新。"""

    retry_count = get_tool_retry_count(state, tool_call_id)
    return {
        "status": "failed",
        "errors": [f"{tool_call_id} reached retry limit after {retry_count} retries."],
        "runtime": {
            "retry_exhausted": {
                tool_call_id: {
                    "retry_count": retry_count,
                    "max_retries": get_tool_rule(tool_call_id).max_retries,
                }
            }
        },
    }
