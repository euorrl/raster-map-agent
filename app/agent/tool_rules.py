from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agent.adjusters import (
    adjust_raster_prepare_plan,
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
    """Agent 层工具后处理规则。

    ToolRule 不执行工具本身，只声明某个工具运行后是否需要 validator
    验收、可恢复失败时是否允许 adjuster 调参，以及最多允许重试几次。
    """

    tool_name: str
    validator: ValidatorFn
    validation_update_builder: ValidationUpdateBuilder
    adjuster: AdjusterFn
    adjustment_update_builder: AdjustmentUpdateBuilder
    max_retries: int = 5
    retryable_status: str = "retryable"


TOOL_RULES: dict[str, ToolRule] = {
    "raster_prepare": ToolRule(
        tool_name="raster_prepare",
        validator=validate_raster_prepare_result,
        validation_update_builder=build_raster_prepare_validation_update,
        adjuster=adjust_raster_prepare_plan,
        adjustment_update_builder=build_raster_prepare_adjustment_update,
        max_retries=5,
    )
}


def get_tool_rule(tool_name: str) -> ToolRule:
    """根据工具结果名读取后处理规则。"""

    try:
        return TOOL_RULES[tool_name]
    except KeyError as error:
        raise ValueError(f"Unsupported tool rule: {tool_name}") from error


def get_tool_retry_count(state: AgentState, tool_name: str) -> int:
    """读取某个工具已经重试的次数。"""

    retry_counts = state.runtime.get("retry_counts", {})
    return int(retry_counts.get(tool_name, 0))


def can_retry_tool(state: AgentState, tool_name: str) -> bool:
    """判断某个工具当前是否还能进入 adjuster 重试。"""

    rule = get_tool_rule(tool_name)
    validators = state.runtime.get("validators", {})
    validation = validators.get(tool_name, {})
    if not isinstance(validation, dict):
        return False
    if validation.get("status") != rule.retryable_status:
        return False

    return get_tool_retry_count(state, tool_name) < rule.max_retries


def build_retry_exhausted_update(state: AgentState, tool_name: str) -> dict[str, Any]:
    """构造工具重试次数耗尽时的 state update。"""

    retry_count = get_tool_retry_count(state, tool_name)
    return {
        "status": "failed",
        "errors": [f"{tool_name} reached retry limit after {retry_count} retries."],
        "runtime": {
            "retry_exhausted": {
                tool_name: {
                    "retry_count": retry_count,
                    "max_retries": get_tool_rule(tool_name).max_retries,
                }
            }
        },
    }
