from pathlib import Path

from app.agent.nodes import answer_node
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

    monkeypatch.setattr(nodes, "create_workspace", fake_create_workspace)
    monkeypatch.setattr(nodes, "prepare_raster_inputs", fake_prepare_raster_inputs)
    monkeypatch.setattr(nodes, "calculate_raster_index", fake_calculate_raster_index)
    monkeypatch.setattr(nodes, "render_index_preview", fake_render_index_preview)

    state = run_workflow("Generate an NDVI vegetation map for Milan.")

    assert state.status == "completed"
    assert state.plan["index_name"] == "NDVI"
    assert state.plan["required_bands"] == ["B04", "B08"]
    assert state.workspace["workspace_dir"] == str(workspace_dir)
    assert state.tool_results["raster_prepare"]["band_paths"]
    assert state.tool_results["index_calculation"]["index_tif_path"]
    assert state.tool_results["render_preview"]["preview_path"]
    assert state.tool_results["metadata_export"]["metadata_path"]
    assert state.final_answer
    assert Path(state.tool_results["metadata_export"]["metadata_path"]).exists()


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
