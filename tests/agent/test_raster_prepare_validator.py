from app.agent.validators import (
    build_raster_prepare_validation_update,
    validate_raster_prepare_result,
)
from app.schemas import AgentState


def test_raster_prepare_validator_passes_valid_result():
    state = AgentState(
        user_query="计算成都 NDVI",
        plan={"required_bands": ["B04", "B08"]},
        tool_results={
            "raster_prepare": {
                "required_bands": ["B04", "B08"],
                "band_paths": {
                    "B04": "data/run/clipped_raster/B04.tif",
                    "B08": "data/run/clipped_raster/B08.tif",
                },
                "diagnostics": {
                    "coverage_status": "covered",
                    "coverage_ratio": 0.92,
                    "min_coverage_ratio": 0.7,
                    "is_retriable": False,
                    "message": "Coverage is acceptable.",
                },
            }
        },
    )

    result = validate_raster_prepare_result(state)

    assert result.status == "passed"
    assert result.should_continue
    assert not result.should_adjust


def test_raster_prepare_validator_routes_retryable_result_to_adjuster():
    state = AgentState(
        user_query="计算成都 NDVI",
        plan={"required_bands": ["B04", "B08"]},
        tool_results={
            "raster_prepare": {
                "required_bands": ["B04", "B08"],
                "band_paths": {},
                "diagnostics": {
                    "coverage_status": "not_covered",
                    "coverage_ratio": 0.52,
                    "min_coverage_ratio": 0.7,
                    "is_retriable": True,
                    "failure_reason": "insufficient_spatial_coverage",
                    "message": "Selected scenes do not cover enough AOI.",
                    "suggested_actions": [
                        "expand_date_range",
                        "increase_max_cloud_cover",
                    ],
                },
            }
        },
    )

    result = validate_raster_prepare_result(state)
    update = build_raster_prepare_validation_update(result)

    assert result.status == "retryable"
    assert result.should_adjust
    assert result.reasons == ["insufficient_spatial_coverage"]
    assert "expand_date_range" in result.suggested_actions
    assert update["status"] == "raster_prepare_retryable"
    assert update["runtime"]["validators"]["raster_prepare"]["status"] == "retryable"


def test_raster_prepare_validator_fails_when_band_path_is_missing():
    state = AgentState(
        user_query="计算成都 NDVI",
        plan={"required_bands": ["B04", "B08"]},
        tool_results={
            "raster_prepare": {
                "required_bands": ["B04", "B08"],
                "band_paths": {
                    "B04": "data/run/clipped_raster/B04.tif",
                },
                "diagnostics": {
                    "coverage_status": "covered",
                    "coverage_ratio": 0.9,
                    "min_coverage_ratio": 0.7,
                    "is_retriable": False,
                    "message": "Coverage is acceptable.",
                },
            }
        },
    )

    result = validate_raster_prepare_result(state)
    update = build_raster_prepare_validation_update(result)

    assert result.status == "failed"
    assert result.reasons == ["missing_band_paths:B08"]
    assert update["status"] == "failed"
    assert update["errors"] == ["missing_band_paths:B08"]


def test_raster_prepare_validator_fails_without_prepare_result():
    state = AgentState(user_query="计算成都 NDVI")

    result = validate_raster_prepare_result(state)

    assert result.status == "failed"
    assert result.reasons == ["missing_raster_prepare_result"]
