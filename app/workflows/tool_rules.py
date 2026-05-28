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
    """Post-tool workflow rule.

    ToolRule does not execute the tool itself. It declares whether a tool result
    needs validation, whether retryable failures can be adjusted, and how many
    retries are allowed.
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
    """Return the post-tool workflow rule for a tool result name."""

    try:
        return TOOL_RULES[tool_name]
    except KeyError as error:
        raise ValueError(f"Unsupported tool rule: {tool_name}") from error


def get_tool_retry_count(state: AgentState, tool_name: str) -> int:
    """Return how many retries have already run for a tool."""

    retry_counts = state.runtime.get("retry_counts", {})
    return int(retry_counts.get(tool_name, 0))


def can_retry_tool(state: AgentState, tool_name: str) -> bool:
    """Return whether a tool can still enter adjust-and-retry flow."""

    rule = get_tool_rule(tool_name)
    validators = state.runtime.get("validators", {})
    validation = validators.get(tool_name, {})
    if not isinstance(validation, dict):
        return False
    if validation.get("status") != rule.retryable_status:
        return False

    return get_tool_retry_count(state, tool_name) < rule.max_retries


def build_retry_exhausted_update(state: AgentState, tool_name: str) -> dict[str, Any]:
    """Build a state update for exhausted tool retries."""

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
