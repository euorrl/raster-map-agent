import pytest

from app.agent.tool_rules import (
    build_retry_exhausted_update,
    can_retry_tool,
    get_agent_tool_policy,
    get_tool_retry_count,
)
from app.agent.adjusters import adjust_raster_prepare_plan
from app.agent.validators import validate_raster_prepare_result
from app.schemas import AgentState


def test_get_agent_tool_policy_returns_raster_prepare_policy():
    policy = get_agent_tool_policy("raster_prepare")

    assert policy.tool_name == "raster_prepare"
    assert policy.validator is validate_raster_prepare_result
    assert policy.adjuster is adjust_raster_prepare_plan
    assert policy.max_retries == 5


def test_get_agent_tool_policy_rejects_unknown_tool():
    with pytest.raises(ValueError, match="Unsupported agent tool policy"):
        get_agent_tool_policy("unknown_tool")


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
