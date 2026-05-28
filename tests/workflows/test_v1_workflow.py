from pathlib import Path

from app.agent.nodes import answer_node
from app.agent.planners import AgentPlanResult
from app.schemas import AgentState
from app.tools.index_calculation import IndexCalculationResult
from app.tools.raster_prepare import RasterPrepareResult, RasterScenePlanDiagnostics
from app.tools.render_preview import RenderPreviewResult
from app.tools.workspace import WorkspaceResult
from app.workflows.workflow import route_after_planning, run_workflow


def test_v1_workflow_completes_real_tool_nodes_with_patched_tools(
    monkeypatch,
    tmp_path,
):
    import app.agent.nodes as nodes

    workspace_dir = tmp_path / "mock_run"

    def fake_build_agent_plan(user_query):
        return AgentPlanResult(
            status="planned",
            plan={
                "route": "raster_product_generate",
                "answer_mode": "metadata_summary",
                "aoi_query": "Milan, Lombardy, Italy",
                "index_name": "NDVI",
                "start_date": "2024-06-01",
                "end_date": "2024-08-31",
                "max_cloud_cover": 20,
            },
            rationale="Mock planner result.",
        )

    def fake_create_workspace(request):
        workspace_dir.mkdir()
        return WorkspaceResult(
            run_id="mock_run",
            workspace_dir=str(workspace_dir),
        )

    def fake_prepare_raster_inputs(request):
        assert request.workspace_dir == workspace_dir
        return RasterPrepareResult(
            workspace_dir=str(workspace_dir),
            output_dir=str(workspace_dir / "output"),
            boundary_geojson_path=str(workspace_dir / "aoi" / "milan.geojson"),
            index_name="NDVI",
            data_source="sentinel2",
            required_bands=["B04", "B08"],
            band_roles={"red": "B04", "nir": "B08"},
            index_formula="(nir - red) / (nir + red)",
            band_paths={
                "B04": str(workspace_dir / "clipped_raster" / "B04_clipped.tif"),
                "B08": str(workspace_dir / "clipped_raster" / "B08_clipped.tif"),
            },
            scene_ids=["mock_scene"],
            diagnostics=RasterScenePlanDiagnostics(
                coverage_status="covered",
                coverage_ratio=1,
                min_coverage_ratio=0.7,
                message="Mock coverage is sufficient.",
                selected_scene_count=1,
            ),
        )

    def fake_calculate_raster_index(request):
        assert request.workspace_dir == workspace_dir
        assert request.band_roles == {"red": "B04", "nir": "B08"}
        return IndexCalculationResult(
            index_tif_path=str(workspace_dir / "output" / "ndvi.tif")
        )

    def fake_render_index_preview(request):
        assert request.index_tif_path == workspace_dir / "output" / "ndvi.tif"
        return RenderPreviewResult(
            preview_path=str(workspace_dir / "output" / "ndvi_preview.png")
        )

    monkeypatch.setattr(nodes, "build_agent_plan", fake_build_agent_plan)
    monkeypatch.setattr(nodes, "create_workspace", fake_create_workspace)
    monkeypatch.setattr(nodes, "prepare_raster_inputs", fake_prepare_raster_inputs)
    monkeypatch.setattr(nodes, "calculate_raster_index", fake_calculate_raster_index)
    monkeypatch.setattr(nodes, "render_index_preview", fake_render_index_preview)

    state = run_workflow("Generate an NDVI vegetation map for Milan.")

    assert state.status == "completed"
    assert state.plan["index_name"] == "NDVI"
    assert "required_bands" not in state.plan
    assert [tool_call["id"] for tool_call in state.tool_calls] == [
        "workspace",
        "raster_prepare",
        "index_calculation",
        "render_preview",
        "metadata_export",
        "answer",
    ]
    assert state.tool_calls[1]["params"]["aoi_query"] == "Milan, Lombardy, Italy"
    assert state.tool_calls[2]["params"]["band_roles"] == {"red": "B04", "nir": "B08"}
    assert state.runtime["registry"]["raster_product"]["required_bands"] == [
        "B04",
        "B08",
    ]
    assert state.workspace["workspace_dir"] == str(workspace_dir)
    assert state.tool_results["raster_prepare"]["band_paths"]
    assert state.tool_results["index_calculation"]["index_tif_path"]
    assert state.tool_results["render_preview"]["preview_path"]
    assert state.tool_results["metadata_export"]["metadata_path"]
    product = state.tool_results["metadata_export"]["product_info"]["product"]
    assert product["type"] == "index"
    assert product["name"] == "NDVI"
    assert state.final_answer
    metadata_path = Path(state.tool_results["metadata_export"]["metadata_path"])
    assert metadata_path.exists()
    assert '"product"' in metadata_path.read_text(encoding="utf-8")


def test_route_after_planning_sends_direct_answer_to_answer_node():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
        status="planned",
    )

    assert route_after_planning(state) == "direct_answer"


def test_answer_node_handles_direct_answer_mode():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
        status="planned",
    )

    update = answer_node(state)

    assert update["status"] == "completed"
    assert update["final_answer"] == "Mock direct answer for: What is remote sensing?"


def test_v1_workflow_compiles_direct_answer_tool_call(monkeypatch):
    import app.agent.nodes as nodes

    def fake_build_agent_plan(user_query):
        return AgentPlanResult(
            status="planned",
            plan={"route": "direct_answer", "answer_mode": "direct_answer"},
            rationale="Mock direct planner result.",
        )

    monkeypatch.setattr(nodes, "build_agent_plan", fake_build_agent_plan)

    state = run_workflow("What is remote sensing?")

    assert state.status == "completed"
    assert state.tool_calls == [
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
