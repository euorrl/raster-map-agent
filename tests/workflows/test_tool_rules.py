import pytest

from app.agent.adjusters import adjust_raster_prepare_plan
from app.agent.validators import validate_raster_prepare_result
from app.schemas import AgentState
from app.workflows.tool_rules import (
    build_retry_exhausted_update,
    can_retry_tool,
    get_tool_retry_count,
    get_tool_rule,
)


def test_get_tool_rule_returns_raster_prepare_rule():
    rule = get_tool_rule("raster_prepare")

    assert rule.tool_name == "raster_prepare"
    assert rule.validator is validate_raster_prepare_result
    assert rule.adjuster is adjust_raster_prepare_plan
    assert rule.max_retries == 5


def test_get_tool_rule_rejects_unknown_tool():
    with pytest.raises(ValueError, match="Unsupported tool rule"):
        get_tool_rule("unknown_tool")


def test_can_retry_tool_requires_retryable_validation_status():
    state = AgentState(
        user_query="计算成都 NDVI",
        runtime={
            "validators": {
                "raster_prepare": {
                    "status": "passed",
                }
            }
        },
    )

    assert not can_retry_tool(state, "raster_prepare")


def test_can_retry_tool_respects_retry_limit():
    state = AgentState(
        user_query="计算成都 NDVI",
        runtime={
            "validators": {
                "raster_prepare": {
                    "status": "retryable",
                }
            },
            "retry_counts": {
                "raster_prepare": 4,
            },
        },
    )

    assert get_tool_retry_count(state, "raster_prepare") == 4
    assert can_retry_tool(state, "raster_prepare")

    state.runtime["retry_counts"]["raster_prepare"] = 5

    assert not can_retry_tool(state, "raster_prepare")


def test_build_retry_exhausted_update_records_runtime_context():
    state = AgentState(
        user_query="计算成都 NDVI",
        runtime={
            "retry_counts": {
                "raster_prepare": 5,
            }
        },
    )

    update = build_retry_exhausted_update(state, "raster_prepare")

    assert update["status"] == "failed"
    assert update["errors"] == ["raster_prepare reached retry limit after 5 retries."]
    assert update["runtime"]["retry_exhausted"]["raster_prepare"] == {
        "retry_count": 5,
        "max_retries": 5,
    }
