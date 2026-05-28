import json
from copy import deepcopy

from app.schemas import AgentState
from app.agent.adjusters import (
    adjust_raster_prepare_tool_call,
    build_raster_prepare_adjustment_update,
    RasterPrepareAdjustmentResult,
)


def make_state(tool_calls=None, validators=None, runtime=None):
    state = AgentState(user_query="test")
    state.tool_calls = tool_calls or []
    state.runtime = runtime or {}
    if validators is not None:
        state.runtime.setdefault("validators", {})
        state.runtime["validators"].update(validators)
    return state


def test_non_retryable_validation_skips():
    state = make_state(
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
                "params": {},
            }
        ],
        validators={"raster_prepare": {"status": "passed"}},
        runtime={"last_tool_index": 0},
    )

    def empty_client(messages):
        return "{}"

    result = adjust_raster_prepare_tool_call(state, client=empty_client)
    assert isinstance(result, RasterPrepareAdjustmentResult)
    assert result.status == "skipped"


def test_empty_suggested_actions_fails():
    state = make_state(
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
                "params": {},
            }
        ],
        validators={"raster_prepare": {"status": "retryable", "suggested_actions": []}},
        runtime={"last_tool_index": 0},
    )

    def empty_client(messages):
        return "{}"

    result = adjust_raster_prepare_tool_call(state, client=empty_client)
    assert result.status == "failed"


def test_adjuster_applies_valid_date_and_cloud_cover_adjustment():
    # current params
    current_params = {
        "start_date": "2024-06-10",
        "end_date": "2024-06-20",
        "max_cloud_cover": 10,
    }

    tool_calls = [
        {"id": "workspace", "tool_name": "workspace.create_workspace", "params": {}},
        {
            "id": "raster_prepare",
            "tool_name": "raster_prepare.prepare_raster_inputs",
            "params": deepcopy(current_params),
        },
    ]

    state = make_state(
        tool_calls=tool_calls,
        validators={
            "raster_prepare": {
                "status": "retryable",
                "suggested_actions": ["expand_date_range", "increase_max_cloud_cover"],
            }
        },
        runtime={"last_tool_index": 1},
    )

    # LLM proposes expanding start_date earlier and increasing cloud cover to 20.
    # The step should be limited by MAX_CLOUD_COVER_STEP.
    proposed = {
        "start_date": "2024-06-01",
        "max_cloud_cover": 20,
        "rationale": "Expand date and allow slightly more cloud",
    }

    def client(messages):
        return json.dumps(proposed)

    result = adjust_raster_prepare_tool_call(state, client=client)

    assert result.status == "adjusted"
    # changed fields should include start_date and max_cloud_cover
    assert set(result.changed_fields) == {"max_cloud_cover", "start_date"}
    # adjusted_params should be a dict and include sanitized values
    assert result.adjusted_params["start_date"] == "2024-06-01"
    # max_cloud_cover should not drop and may increase by at most MAX_CLOUD_COVER_STEP
    assert (
        result.adjusted_params["max_cloud_cover"] >= current_params["max_cloud_cover"]
    )
    assert (
        result.adjusted_params["max_cloud_cover"]
        <= current_params["max_cloud_cover"] + 5
    )


def test_max_cloud_cover_cannot_decrease_and_limited():
    current_params = {"max_cloud_cover": 25}
    tool_calls = [
        {
            "id": "raster_prepare",
            "tool_name": "raster_prepare.prepare_raster_inputs",
            "params": deepcopy(current_params),
        }
    ]

    # propose a decrease and excessive increase
    proposed = {"max_cloud_cover": 5}

    state = make_state(
        tool_calls=tool_calls,
        validators={
            "raster_prepare": {
                "status": "retryable",
                "suggested_actions": ["increase_max_cloud_cover"],
            }
        },
        runtime={"last_tool_index": 0},
    )

    def client(messages):
        return json.dumps(proposed)

    result = adjust_raster_prepare_tool_call(state, client=client)

    # decrease should be ignored -> no change
    assert result.status == "skipped" or (
        result.changed_fields == []
    ), "Decrease should be ignored"


def test_build_adjustment_update_applies_changes_and_records_history():
    current_params = {"start_date": "2024-06-10", "max_cloud_cover": 10}
    tool_calls = [
        {
            "id": "raster_prepare",
            "tool_name": "raster_prepare.prepare_raster_inputs",
            "params": deepcopy(current_params),
        }
    ]
    state = make_state(
        tool_calls=tool_calls,
        validators={
            "raster_prepare": {
                "status": "retryable",
                "suggested_actions": ["expand_date_range"],
            }
        },
        runtime={"last_tool_index": 0, "adjustments": [{"existing": True}]},
    )

    result = RasterPrepareAdjustmentResult(
        status="adjusted",
        adjusted_params={"start_date": "2024-06-01", "max_cloud_cover": 10},
        changed_fields=["start_date"],
        rationale="expand",
    )

    update = build_raster_prepare_adjustment_update(state, result)

    assert "plan" not in update
    assert update.get("tool_calls") is not None
    assert update["tool_calls"][0]["params"]["start_date"] == "2024-06-01"
    assert update["runtime"]["current_tool_index"] == 0
    assert update["runtime"]["retry_counts"]["raster_prepare"] >= 0
    assert isinstance(update["runtime"]["adjustments"], list)
    # adjustments should append to existing adjustments
    assert update["runtime"]["adjustments"][-1]["tool_call_id"] == "raster_prepare"
    assert update["status"] == "raster_prepare_adjusted"


def test_missing_or_oob_last_tool_index_fails():
    state = make_state(
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
                "params": {},
            }
        ],
        validators={
            "raster_prepare": {
                "status": "retryable",
                "suggested_actions": ["expand_date_range"],
            }
        },
        runtime={},
    )
    # missing last_tool_index

    def empty_client(messages):
        return json.dumps({})

    res = adjust_raster_prepare_tool_call(state, client=empty_client)
    assert res.status == "failed"

    # out of bounds
    state.runtime["last_tool_index"] = 10
    res2 = adjust_raster_prepare_tool_call(state, client=empty_client)
    assert res2.status == "failed"


def test_last_tool_call_id_mismatch_fails():
    state = make_state(
        tool_calls=[{"id": "not_raster", "tool_name": "x", "params": {}}],
        validators={
            "raster_prepare": {
                "status": "retryable",
                "suggested_actions": ["expand_date_range"],
            }
        },
        runtime={"last_tool_index": 0},
    )

    def empty_client(messages):
        return json.dumps({})

    res = adjust_raster_prepare_tool_call(state, client=empty_client)
    assert res.status == "failed"
