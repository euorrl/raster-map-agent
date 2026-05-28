from app.agent.adjusters import (
    adjust_raster_prepare_plan,
    build_raster_prepare_adjustment_update,
)
from app.schemas import AgentState


def test_raster_prepare_adjuster_updates_allowed_fields():
    state = _retryable_state(
        suggested_actions=[
            "expand_date_range",
            "increase_max_cloud_cover",
        ]
    )

    def fake_client(messages):
        assert messages[0]["role"] == "system"
        return """
        {
          "start_date": "2024-05-01",
          "end_date": "2024-09-30",
          "max_cloud_cover": 45,
          "scene_limit": 100,
          "max_selected_scenes": 30,
          "rationale": "Expand search space after low coverage."
        }
        """

    result = adjust_raster_prepare_plan(state, client=fake_client)
    update = build_raster_prepare_adjustment_update(state, result)

    assert result.status == "adjusted"
    assert result.adjusted_plan["start_date"] == "2024-05-01"
    assert result.adjusted_plan["end_date"] == "2024-09-30"
    assert result.adjusted_plan["max_cloud_cover"] == 25
    assert result.adjusted_plan["scene_limit"] == 80
    assert result.adjusted_plan["max_selected_scenes"] == 20
    assert update["status"] == "raster_prepare_adjusted"
    assert update["runtime"]["retry_counts"]["raster_prepare"] == 1


def test_raster_prepare_adjuster_fails_when_only_limit_action_is_suggested():
    state = _retryable_state(suggested_actions=["increase_limit"])

    result = adjust_raster_prepare_plan(state, client=lambda messages: "{}")

    assert result.status == "failed"
    assert result.error == "No supported adjustment actions were suggested."


def test_raster_prepare_adjuster_ignores_limit_fields():
    state = _retryable_state(suggested_actions=["increase_max_cloud_cover"])

    def fake_client(messages):
        return """
        {
          "max_cloud_cover": 45,
          "scene_limit": 100,
          "max_selected_scenes": 30,
          "rationale": "Only cloud cover can be changed."
        }
        """

    result = adjust_raster_prepare_plan(state, client=fake_client)

    assert result.status == "adjusted"
    assert result.changed_fields == ["max_cloud_cover"]
    assert result.adjusted_plan["max_cloud_cover"] == 25
    assert result.adjusted_plan["scene_limit"] == 80
    assert result.adjusted_plan["max_selected_scenes"] == 20


def test_raster_prepare_adjuster_skips_non_retryable_state():
    state = AgentState(
        user_query="计算成都 NDVI",
        plan=_base_plan(),
        runtime={
            "validators": {
                "raster_prepare": {
                    "status": "passed",
                }
            }
        },
    )

    result = adjust_raster_prepare_plan(state, client=lambda messages: "{}")
    update = build_raster_prepare_adjustment_update(state, result)

    assert result.status == "skipped"
    assert update["status"] == "raster_prepare_adjustment_skipped"


def test_raster_prepare_adjuster_fails_on_invalid_llm_json():
    state = _retryable_state(suggested_actions=["increase_max_cloud_cover"])

    result = adjust_raster_prepare_plan(
        state,
        client=lambda messages: "not json",
    )

    assert result.status == "failed"
    assert result.error == "LLM response is not valid JSON."


def test_raster_prepare_adjuster_warns_on_no_valid_changes():
    state = _retryable_state(suggested_actions=["increase_max_cloud_cover"])

    result = adjust_raster_prepare_plan(
        state,
        client=lambda messages: '{"max_cloud_cover": 10}',
    )
    update = build_raster_prepare_adjustment_update(state, result)

    assert result.status == "skipped"
    assert result.warnings == [
        "LLM response did not contain any valid plan adjustment."
    ]
    assert update["status"] == "raster_prepare_adjustment_skipped"
    assert update["warnings"] == [
        "LLM response did not contain any valid plan adjustment."
    ]


def test_raster_prepare_adjuster_caps_cloud_cover_at_30():
    state = _retryable_state(suggested_actions=["increase_max_cloud_cover"])
    state.plan["max_cloud_cover"] = 28

    result = adjust_raster_prepare_plan(
        state,
        client=lambda messages: '{"max_cloud_cover": 80}',
    )

    assert result.status == "adjusted"
    assert result.adjusted_plan["max_cloud_cover"] == 30


def _retryable_state(suggested_actions):
    return AgentState(
        user_query="计算成都 NDVI",
        plan=_base_plan(),
        runtime={
            "validators": {
                "raster_prepare": {
                    "status": "retryable",
                    "reasons": ["insufficient_spatial_coverage"],
                    "suggested_actions": suggested_actions,
                    "diagnostics": {
                        "coverage_status": "not_covered",
                        "coverage_ratio": 0.52,
                        "min_coverage_ratio": 0.7,
                    },
                }
            }
        },
    )


def _base_plan():
    return {
        "aoi_query": "Chengdu, Sichuan, China",
        "index_name": "NDVI",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
        "scene_limit": 80,
        "max_selected_scenes": 20,
    }
