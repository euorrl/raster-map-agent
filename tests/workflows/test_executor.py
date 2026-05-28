import pytest

from pydantic import BaseModel

from app.schemas import AgentState
from app.tools.answer import FinalAnswerRequest, FinalAnswerResult
from app.tools.index_calculation import IndexCalculationRequest, IndexCalculationResult
from app.tools.metadata import MetadataExportRequest, MetadataExportResult
from app.tools.raster_prepare import (
    RasterPrepareRequest,
    RasterPrepareResult,
    RasterScenePlanDiagnostics,
)
from app.tools.render_preview import RenderPreviewRequest, RenderPreviewResult
from app.tools.workspace import WorkspaceRequest, WorkspaceResult
from app.workflows.compiler import compile_tool_calls
from app.workflows.executor import (
    ToolExecutionError,
    ToolSpec,
    execute_current_tool_call,
    execute_tool_calls,
)


def test_execute_direct_answer_tool_call_with_injected_tool():
    def fake_answer(request):
        assert isinstance(request, FinalAnswerRequest)
        assert request.answer_mode == "direct_answer"
        assert request.question == "What is remote sensing?"
        return FinalAnswerResult(final_answer="Remote sensing answer.")

    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
    )
    state.tool_calls = compile_tool_calls(state)

    result = execute_tool_calls(
        state,
        tool_specs={
            "answer.generate_final_answer": ToolSpec(
                tool_name="answer.generate_final_answer",
                request_model=FinalAnswerRequest,
                tool_fn=fake_answer,
                result_target="final_answer",
            )
        },
    )

    assert result.final_answer == "Remote sensing answer."
    assert result.status == "completed"
    assert result.runtime["executor"]["executed_tool_calls"] == ["answer"]


def test_execute_current_tool_call_executes_single_tool_and_advances_index():
    class DummyRequest(BaseModel):
        value: str

    class DummyResult(BaseModel):
        output: str

    def fake_dummy(request):
        assert isinstance(request, DummyRequest)
        return DummyResult(output=request.value.upper())

    state = AgentState(user_query="hello world", runtime={"current_tool_index": 0})
    state.tool_calls = [
        {
            "id": "dummy",
            "tool_name": "dummy.execute",
            "params": {"value": "hello"},
            "result_key": "dummy",
        }
    ]

    result = execute_current_tool_call(
        state,
        tool_specs={
            "dummy.execute": ToolSpec(
                tool_name="dummy.execute",
                request_model=DummyRequest,
                tool_fn=fake_dummy,
            )
        },
    )

    assert result.tool_results["dummy"]["output"] == "HELLO"
    assert result.runtime["current_tool_index"] == 1
    assert result.runtime["last_tool_index"] == 0
    assert result.runtime["last_tool_call_id"] == "dummy"
    assert result.runtime["last_tool_name"] == "dummy.execute"
    assert result.status == "tool_executed"


def test_execute_current_tool_call_resolves_state_references():
    class DummyRequest(BaseModel):
        question: str

    class DummyResult(BaseModel):
        answer: str

    def fake_dummy(request):
        assert isinstance(request, DummyRequest)
        return DummyResult(answer=request.question)

    state = AgentState(
        user_query="Why is the sky blue?", runtime={"current_tool_index": 0}
    )
    state.tool_calls = [
        {
            "id": "dummy",
            "tool_name": "dummy.execute",
            "params": {"question": "$state.user_query"},
            "result_key": "dummy",
        }
    ]

    result = execute_current_tool_call(
        state,
        tool_specs={
            "dummy.execute": ToolSpec(
                tool_name="dummy.execute",
                request_model=DummyRequest,
                tool_fn=fake_dummy,
            )
        },
    )

    assert result.tool_results["dummy"]["answer"] == "Why is the sky blue?"
    assert result.runtime["current_tool_index"] == 1


def test_execute_current_tool_call_returns_no_more_tools_when_index_out_of_range():
    state = AgentState(user_query="no more", runtime={"current_tool_index": 1})
    state.tool_calls = [
        {
            "id": "dummy",
            "tool_name": "dummy.execute",
            "params": {"value": "hello"},
            "result_key": "dummy",
        }
    ]

    result = execute_current_tool_call(state)

    assert result.status == "no_more_tools"


def test_execute_raster_product_tool_calls_with_injected_tools(tmp_path):
    workspace_dir = tmp_path / "run_1"

    def fake_workspace(request):
        assert isinstance(request, WorkspaceRequest)
        return WorkspaceResult(run_id="run_1", workspace_dir=str(workspace_dir))

    def fake_raster_prepare(request):
        assert isinstance(request, RasterPrepareRequest)
        assert request.workspace_dir == workspace_dir
        assert request.aoi_query == "Chengdu, Sichuan, China"
        return RasterPrepareResult(
            workspace_dir=str(workspace_dir),
            output_dir=str(workspace_dir / "output"),
            boundary_geojson_path=str(workspace_dir / "aoi" / "chengdu.geojson"),
            index_name="NDVI",
            data_source="sentinel2",
            provider="earth_search",
            collection="sentinel-2-l2a",
            required_bands=["B04", "B08"],
            band_roles={"red": "B04", "nir": "B08"},
            index_formula="(nir - red) / (nir + red)",
            band_paths={
                "B04": str(workspace_dir / "clipped_raster" / "B04_clipped.tif"),
                "B08": str(workspace_dir / "clipped_raster" / "B08_clipped.tif"),
            },
            scene_ids=["scene_1"],
            diagnostics=RasterScenePlanDiagnostics(
                coverage_status="covered",
                coverage_ratio=1,
                min_coverage_ratio=0.7,
                message="covered",
            ),
        )

    def fake_index_calculation(request):
        assert isinstance(request, IndexCalculationRequest)
        assert request.workspace_dir == workspace_dir
        assert request.band_roles == {"red": "B04", "nir": "B08"}
        return IndexCalculationResult(
            index_tif_path=str(workspace_dir / "output" / "ndvi.tif")
        )

    def fake_render_preview(request):
        assert isinstance(request, RenderPreviewRequest)
        assert request.index_tif_path == workspace_dir / "output" / "ndvi.tif"
        return RenderPreviewResult(
            preview_path=str(workspace_dir / "output" / "ndvi_preview.png")
        )

    def fake_metadata(request):
        assert isinstance(request, MetadataExportRequest)
        workflow_state = request.workflow_state
        assert workflow_state["tool_results"]["raster_prepare"]["index_name"] == "NDVI"
        assert workflow_state["tool_results"]["index_calculation"][
            "index_tif_path"
        ] == str(workspace_dir / "output" / "ndvi.tif")
        return MetadataExportResult(
            metadata_path=str(workspace_dir / "output" / "metadata.json"),
            product_info={"product": {"type": "index", "name": "NDVI"}},
        )

    def fake_answer(request):
        assert isinstance(request, FinalAnswerRequest)
        assert request.answer_mode == "metadata_summary"
        assert request.metadata == {"product": {"type": "index", "name": "NDVI"}}
        return FinalAnswerResult(final_answer="NDVI generated.")

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
    state.tool_calls = compile_tool_calls(state)

    result = execute_tool_calls(
        state,
        tool_specs={
            "workspace.create_workspace": ToolSpec(
                "workspace.create_workspace",
                WorkspaceRequest,
                fake_workspace,
                "workspace",
            ),
            "raster_prepare.prepare_raster_inputs": ToolSpec(
                "raster_prepare.prepare_raster_inputs",
                RasterPrepareRequest,
                fake_raster_prepare,
            ),
            "index_calculation.calculate_raster_index": ToolSpec(
                "index_calculation.calculate_raster_index",
                IndexCalculationRequest,
                fake_index_calculation,
            ),
            "render_preview.render_index_preview": ToolSpec(
                "render_preview.render_index_preview",
                RenderPreviewRequest,
                fake_render_preview,
            ),
            "metadata.export_metadata": ToolSpec(
                "metadata.export_metadata",
                MetadataExportRequest,
                fake_metadata,
            ),
            "answer.generate_final_answer": ToolSpec(
                "answer.generate_final_answer",
                FinalAnswerRequest,
                fake_answer,
                "final_answer",
            ),
        },
    )

    assert result.workspace["workspace_dir"] == str(workspace_dir)
    assert result.tool_results["raster_prepare"]["index_name"] == "NDVI"
    assert result.tool_results["index_calculation"]["index_tif_path"].endswith(
        "ndvi.tif"
    )
    assert result.tool_results["metadata_export"]["product_info"] == {
        "product": {"type": "index", "name": "NDVI"}
    }
    assert result.final_answer == "NDVI generated."
    assert result.runtime["executor"]["executed_tool_calls"] == [
        "workspace",
        "raster_prepare",
        "index_calculation",
        "render_preview",
        "metadata_export",
        "answer",
    ]


def test_execute_tool_calls_rejects_unmet_dependency():
    state = AgentState(user_query="test")
    state.tool_calls = [
        {
            "id": "second",
            "tool_name": "answer.generate_final_answer",
            "params": {
                "answer_mode": "direct_answer",
                "question": "$state.user_query",
            },
            "depends_on": ["first"],
            "result_key": "final_answer",
        }
    ]

    with pytest.raises(ToolExecutionError, match="unmet dependencies"):
        execute_tool_calls(state)


def test_execute_tool_calls_rejects_missing_state_reference():
    def fake_answer(request):
        return FinalAnswerResult(final_answer="answer")

    state = AgentState(user_query="test")
    state.tool_calls = [
        {
            "id": "answer",
            "tool_name": "answer.generate_final_answer",
            "params": {
                "answer_mode": "direct_answer",
                "question": "$state.missing",
            },
            "depends_on": [],
            "result_key": "final_answer",
        }
    ]

    with pytest.raises(ToolExecutionError, match="cannot be resolved"):
        execute_tool_calls(
            state,
            tool_specs={
                "answer.generate_final_answer": ToolSpec(
                    "answer.generate_final_answer",
                    FinalAnswerRequest,
                    fake_answer,
                    "final_answer",
                )
            },
        )
