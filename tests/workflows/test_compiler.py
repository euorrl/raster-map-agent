import pytest

from app.schemas import AgentState
from app.workflows.compiler import compile_tool_calls


def test_compile_raster_product_tool_calls_uses_plan_and_registry_params():
    state = AgentState(
        user_query="Generate NDVI for Chengdu.",
        plan={
            "route": "raster_product_generate",
            "answer_mode": "metadata_summary",
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "NDVI",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 20,
        },
        runtime={
            "registry": {
                "raster_product": {
                    "data_source": "sentinel2",
                    "band_roles": {"red": "B04", "nir": "B08"},
                    "index_formula": "(nir - red) / (nir + red)",
                }
            }
        },
    )

    tool_calls = compile_tool_calls(state)

    assert [tool_call["id"] for tool_call in tool_calls] == [
        "workspace",
        "raster_prepare",
        "index_calculation",
        "render_preview",
        "metadata_export",
        "answer",
    ]
    raster_prepare = tool_calls[1]
    assert raster_prepare["tool_name"] == "raster_prepare.prepare_raster_inputs"
    assert raster_prepare["params"] == {
        "aoi_query": "Chengdu, Sichuan, China",
        "index_name": "NDVI",
        "data_source": "sentinel2",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
        "workspace_dir": "$state.workspace.workspace_dir",
    }
    index_calculation = tool_calls[2]
    assert index_calculation["params"]["band_roles"] == {
        "red": "B04",
        "nir": "B08",
    }
    assert index_calculation["params"]["index_formula"] == (
        "(nir - red) / (nir + red)"
    )
    assert tool_calls[4]["params"] == {
        "workspace_dir": "$state.workspace.workspace_dir",
        "workflow_state": "$state",
    }
    assert tool_calls[5]["params"]["metadata"] == (
        "$state.tool_results.metadata_export.product_info"
    )


def test_compile_direct_answer_tool_calls_skips_raster_tools():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
    )

    tool_calls = compile_tool_calls(state)

    assert tool_calls == [
        {
            "id": "answer",
            "tool_name": "answer.generate_final_answer",
            "params": {
                "answer_mode": "direct_answer",
                "question": "$state.user_query",
            },
            "depends_on": [],
            "result_key": "final_answer",
        }
    ]


def test_compile_raster_product_requires_registry_params():
    state = AgentState(
        user_query="Generate NDVI for Chengdu.",
        plan={
            "route": "raster_product_generate",
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "NDVI",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
        },
    )

    with pytest.raises(ValueError, match="runtime.registry.raster_product"):
        compile_tool_calls(state)
