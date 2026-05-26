from app.workflows.v1_workflow import run_v1_workflow


def test_v1_workflow_completes_mock_ndvi_request():
    # 验证 V1 mock workflow 能完整跑通一个 NDVI 请求。
    state = run_v1_workflow("Generate an NDVI vegetation map for Milan.")

    assert state.status == "completed"
    assert state.plan["index_name"] == "NDVI"
    assert state.plan["required_bands"] == ["B04", "B08"]
    assert state.tool_results["render_preview"]["preview_path"]
    assert state.final_answer
    assert state.metadata["plan"]["aoi_query"] == "Milan"
    assert state.warnings == [
        "Using mock AOI bounding box for Milan.",
        "Using mock Sentinel-2 band paths.",
    ]
