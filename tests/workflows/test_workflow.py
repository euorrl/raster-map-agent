from pathlib import Path

from app.agent.nodes import answer_node
from app.agent.planners import AgentPlanResult
from app.schemas import AgentState
from app.tools.answer.schemas import FinalAnswerResult
from app.tools.index_calculation import IndexCalculationResult
from app.tools.raster_prepare import RasterPrepareResult, RasterScenePlanDiagnostics
from app.tools.render_preview import RenderPreviewResult
from app.tools.workspace import WorkspaceResult
from app.workflows import executor
from app.workflows import workflow as workflow_module
from app.workflows.executor import ToolSpec
from app.workflows.workflow import (
    route_after_adjustment,
    route_after_compilation,
    route_after_planning,
    route_after_registry,
    route_after_tool_execution,
    route_after_validation,
    run_workflow,
)


def test_workflow_completes_real_tool_nodes_with_patched_tools(
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

    patched_tool_specs = executor.TOOL_SPECS.copy()
    workspace_spec = executor.TOOL_SPECS["workspace.create_workspace"]
    raster_prepare_spec = executor.TOOL_SPECS["raster_prepare.prepare_raster_inputs"]
    index_calculation_spec = executor.TOOL_SPECS[
        "index_calculation.calculate_raster_index"
    ]
    render_preview_spec = executor.TOOL_SPECS["render_preview.render_index_preview"]
    answer_spec = executor.TOOL_SPECS["answer.generate_final_answer"]

    patched_tool_specs["workspace.create_workspace"] = ToolSpec(
        tool_name=workspace_spec.tool_name,
        request_model=workspace_spec.request_model,
        tool_fn=fake_create_workspace,
        result_target=workspace_spec.result_target,
    )
    patched_tool_specs["raster_prepare.prepare_raster_inputs"] = ToolSpec(
        tool_name=raster_prepare_spec.tool_name,
        request_model=raster_prepare_spec.request_model,
        tool_fn=fake_prepare_raster_inputs,
        result_target=raster_prepare_spec.result_target,
    )
    patched_tool_specs["index_calculation.calculate_raster_index"] = ToolSpec(
        tool_name=index_calculation_spec.tool_name,
        request_model=index_calculation_spec.request_model,
        tool_fn=fake_calculate_raster_index,
        result_target=index_calculation_spec.result_target,
    )
    patched_tool_specs["render_preview.render_index_preview"] = ToolSpec(
        tool_name=render_preview_spec.tool_name,
        request_model=render_preview_spec.request_model,
        tool_fn=fake_render_index_preview,
        result_target=render_preview_spec.result_target,
    )

    def fake_generate_final_answer(request):
        return FinalAnswerResult(
            final_answer="Mock final answer from patched answer tool."
        )

    patched_tool_specs["answer.generate_final_answer"] = ToolSpec(
        tool_name=answer_spec.tool_name,
        request_model=answer_spec.request_model,
        tool_fn=fake_generate_final_answer,
        result_target=answer_spec.result_target,
    )

    monkeypatch.setattr(executor, "TOOL_SPECS", patched_tool_specs)

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
    assert state.tool_calls[2]["params"]["band_roles"] == {
        "red": "B04",
        "nir": "B08",
    }
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


def test_route_after_planning_sends_direct_answer_to_compiler_route():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
        status="planned",
    )

    assert route_after_planning(state) == "direct_answer"


def test_failed_status_routes_to_failed_branch():
    state = AgentState(
        user_query="Broken request.",
        plan={"route": "raster_product_generate"},
        tool_calls=[
            {
                "id": "answer",
                "tool_name": "answer.generate_final_answer",
                "params": {},
            }
        ],
        runtime={
            "last_tool_call_id": "answer",
            "validators": {"answer": {"status": "passed"}},
        },
        status="failed",
    )

    assert route_after_planning(state) == "failed"
    assert route_after_registry(state) == "failed"
    assert route_after_compilation(state) == "failed"
    assert route_after_tool_execution(state) == "failed"
    assert route_after_validation(state) == "failed"
    assert route_after_adjustment(state) == "failed"


def test_route_after_planning_defaults_to_raster_route():
    state = AgentState(
        user_query="Generate NDVI.",
        plan={"route": "raster_product_generate"},
        status="planned",
    )

    assert route_after_planning(state) == "raster_product_generate"


def test_route_after_registry_success():
    state = AgentState(
        user_query="Generate NDVI.",
        plan={"route": "raster_product_generate"},
        status="planned",
    )

    assert route_after_registry(state) == "ok"


def test_route_after_compilation_requires_tool_calls():
    assert (
        route_after_compilation(
            AgentState(
                user_query="No compiled calls yet.",
                plan={"route": "direct_answer"},
                status="planned",
            )
        )
        == "failed"
    )

    assert (
        route_after_compilation(
            AgentState(
                user_query="Compiled answer call.",
                plan={"route": "direct_answer"},
                tool_calls=[
                    {
                        "id": "answer",
                        "tool_name": "answer.generate_final_answer",
                        "params": {},
                    }
                ],
                status="planned",
            )
        )
        == "ok"
    )


def test_route_after_tool_execution_validates_rule_bound_tool_call():
    state = AgentState(
        user_query="Generate NDVI.",
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
                "params": {},
            },
            {
                "id": "index_calculation",
                "tool_name": "index_calculation.calculate_raster_index",
                "params": {},
            },
        ],
        runtime={
            "last_tool_call_id": "raster_prepare",
            "current_tool_index": 1,
        },
        status="planned",
    )

    assert route_after_tool_execution(state) == "validate"


def test_route_after_tool_execution_continues_or_finishes_without_rule():
    state = AgentState(
        user_query="Generate NDVI.",
        tool_calls=[
            {"id": "workspace", "tool_name": "workspace.create_workspace"},
            {"id": "answer", "tool_name": "answer.generate_final_answer"},
        ],
        runtime={"last_tool_call_id": "workspace", "current_tool_index": 1},
        status="planned",
    )

    assert route_after_tool_execution(state) == "continue"

    state.runtime["last_tool_call_id"] = "answer"
    state.runtime["current_tool_index"] = 2

    assert route_after_tool_execution(state) == "done"


def test_route_after_validation_uses_validator_status():
    state = AgentState(
        user_query="Generate NDVI.",
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
            },
            {
                "id": "index_calculation",
                "tool_name": "index_calculation.calculate_raster_index",
            },
        ],
        runtime={
            "last_tool_call_id": "raster_prepare",
            "current_tool_index": 1,
            "validators": {"raster_prepare": {"status": "passed"}},
        },
        status="planned",
    )

    assert route_after_validation(state) == "continue"

    state.runtime["validators"]["raster_prepare"]["status"] = "retryable"

    assert route_after_validation(state) == "adjust"


def test_route_after_validation_returns_done_after_last_passed_tool():
    state = AgentState(
        user_query="Generate NDVI.",
        tool_calls=[
            {
                "id": "raster_prepare",
                "tool_name": "raster_prepare.prepare_raster_inputs",
            }
        ],
        runtime={
            "last_tool_call_id": "raster_prepare",
            "current_tool_index": 1,
            "validators": {"raster_prepare": {"status": "passed"}},
        },
        status="planned",
    )

    assert route_after_validation(state) == "done"


def test_route_after_validation_supports_latest_fallback():
    state = AgentState(
        user_query="Validate latest.",
        runtime={"validators": {"latest": {"status": "retryable"}}},
        status="planned",
    )

    assert route_after_validation(state) == "adjust"


def test_route_after_validation_fails_without_supported_status():
    state = AgentState(
        user_query="Validate invalid status.",
        runtime={
            "last_tool_call_id": "raster_prepare",
            "validators": {"raster_prepare": {"status": "unknown"}},
        },
        status="planned",
    )

    assert route_after_validation(state) == "failed"


def test_route_after_adjustment_accepts_adjusted_statuses():
    assert (
        route_after_adjustment(
            AgentState(user_query="Adjusted.", status="raster_prepare_adjusted")
        )
        == "adjusted"
    )
    assert (
        route_after_adjustment(
            AgentState(user_query="Tool adjusted.", status="tool_adjusted")
        )
        == "adjusted"
    )
    assert (
        route_after_adjustment(AgentState(user_query="Not adjusted.", status="planned"))
        == "failed"
    )


def test_answer_node_handles_direct_answer_fallback():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"route": "direct_answer", "answer_mode": "direct_answer"},
        status="planned",
    )

    update = answer_node(state)

    assert update["status"] == "completed"
    assert (
        update["final_answer"]
        == "Unable to generate a direct answer for: What is remote sensing?"
    )


def test_workflow_compiles_direct_answer_tool_call(monkeypatch):
    import app.agent.nodes as nodes

    def fake_build_agent_plan(user_query):
        return AgentPlanResult(
            status="planned",
            plan={"route": "direct_answer", "answer_mode": "direct_answer"},
            rationale="Mock direct planner result.",
        )

    monkeypatch.setattr(nodes, "build_agent_plan", fake_build_agent_plan)

    def fake_generate_final_answer(request):
        return FinalAnswerResult(
            final_answer="Mock direct answer for: What is remote sensing?"
        )

    patched_tool_specs = executor.TOOL_SPECS.copy()
    answer_spec = executor.TOOL_SPECS["answer.generate_final_answer"]
    patched_tool_specs["answer.generate_final_answer"] = ToolSpec(
        tool_name=answer_spec.tool_name,
        request_model=answer_spec.request_model,
        tool_fn=fake_generate_final_answer,
        result_target=answer_spec.result_target,
    )
    monkeypatch.setattr(executor, "TOOL_SPECS", patched_tool_specs)

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


def test_apply_update_merges_state_sections_and_appends_messages():
    state = AgentState(
        user_query="Merge update.",
        plan={"a": {"x": 1}},
        tool_results={"old": {"value": 1}},
        errors=["old error"],
        warnings=["old warning"],
    )

    updated = workflow_module._apply_update(
        state,
        {
            "plan": {"a": {"y": 2}},
            "tool_results": {"new": {"value": 2}},
            "tool_calls": [{"id": "answer"}],
            "errors": ["new error"],
            "warnings": ["new warning"],
            "status": "planned",
        },
    )

    assert updated.plan["a"] == {"x": 1, "y": 2}
    assert updated.tool_results["old"]["value"] == 1
    assert updated.tool_results["new"]["value"] == 2
    assert updated.tool_calls == [{"id": "answer"}]
    assert updated.errors == ["old error", "new error"]
    assert updated.warnings == ["old warning", "new warning"]
    assert updated.status == "planned"


def test_build_workflow_returns_linear_fallback_without_langgraph(monkeypatch):
    monkeypatch.setattr(workflow_module, "StateGraph", None)

    workflow = workflow_module.build_workflow()

    assert isinstance(workflow, workflow_module._LinearWorkflow)


def test_linear_workflow_returns_answer_when_planner_fails(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {"status": "failed", "errors": ["planner failed"]},
    )

    state = runner.invoke(AgentState(user_query="Bad request."))

    assert state.status == "failed"
    assert state.final_answer == "Workflow failed: planner failed"


def test_linear_workflow_fails_when_compiler_produces_no_tool_calls(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {
            "status": "planned",
            "plan": {"route": "direct_answer", "answer_mode": "direct_answer"},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "compiler_node",
        lambda state: {"tool_calls": []},
    )

    state = runner.invoke(AgentState(user_query="No compiled calls."))

    assert state.status == "completed"
    assert state.final_answer == (
        "Unable to generate a direct answer for: No compiled calls."
    )


def test_linear_workflow_stops_on_max_steps(monkeypatch):
    runner = workflow_module._LinearWorkflow()
    runner.max_steps = 2

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {
            "status": "planned",
            "plan": {"route": "direct_answer", "answer_mode": "direct_answer"},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "compiler_node",
        lambda state: {
            "tool_calls": [
                {
                    "id": "loop",
                    "tool_name": "loop.tool",
                    "params": {},
                }
            ],
            "runtime": {"current_tool_index": 0},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_executor_node",
        lambda state: {
            "runtime": {"last_tool_call_id": "loop", "current_tool_index": 0}
        },
    )

    state = runner.invoke(AgentState(user_query="Loop forever."))

    assert state.status == "failed"
    assert "exceeded max_steps=2" in state.final_answer


def test_linear_workflow_finishes_after_executor_done(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {
            "status": "planned",
            "plan": {"route": "direct_answer", "answer_mode": "direct_answer"},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "compiler_node",
        lambda state: {
            "tool_calls": [
                {
                    "id": "answer",
                    "tool_name": "answer.generate_final_answer",
                    "params": {},
                }
            ],
            "runtime": {"current_tool_index": 0},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_executor_node",
        lambda state: {
            "final_answer": "Executor final answer.",
            "status": "completed",
            "runtime": {"last_tool_call_id": "answer", "current_tool_index": 1},
        },
    )

    state = runner.invoke(AgentState(user_query="Direct answer."))

    assert state.status == "completed"
    assert state.final_answer == "Executor final answer."


def test_linear_workflow_stops_when_executor_fails(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {
            "status": "planned",
            "plan": {"route": "direct_answer", "answer_mode": "direct_answer"},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "compiler_node",
        lambda state: {
            "tool_calls": [{"id": "answer", "tool_name": "answer.tool"}],
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_executor_node",
        lambda state: {"status": "failed", "errors": ["executor failed"]},
    )

    state = runner.invoke(AgentState(user_query="Executor failure."))

    assert state.status == "failed"
    assert state.final_answer == "Workflow failed: executor failed"


def test_linear_workflow_stops_when_validation_fails(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    _patch_linear_workflow_until_raster_prepare_validation(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "tool_validator_node",
        lambda state: {"status": "failed", "errors": ["validator failed"]},
    )

    state = runner.invoke(AgentState(user_query="Validator failure."))

    assert state.status == "failed"
    assert state.final_answer == "Workflow failed: validator failed"


def test_linear_workflow_finishes_when_validation_passes_last_tool(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    _patch_linear_workflow_until_raster_prepare_validation(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "tool_validator_node",
        lambda state: {
            "runtime": {"validators": {"raster_prepare": {"status": "passed"}}}
        },
    )

    state = runner.invoke(AgentState(user_query="Validator done."))

    assert state.status == "completed"
    assert state.final_answer == (
        "Unable to generate a direct answer for: Validator done."
    )


def test_linear_workflow_retries_after_adjustment(monkeypatch):
    runner = workflow_module._LinearWorkflow()
    executor_calls = []

    _patch_linear_workflow_until_raster_prepare_validation(
        monkeypatch,
        executor_calls=executor_calls,
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_validator_node",
        lambda state: {
            "runtime": {"validators": {"raster_prepare": {"status": "retryable"}}}
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_adjuster_node",
        lambda state: {
            "status": "raster_prepare_adjusted",
            "runtime": {"current_tool_index": 0},
        },
    )

    state = runner.invoke(AgentState(user_query="Adjust and retry."))

    assert len(executor_calls) == 2
    assert state.status == "completed"
    assert state.final_answer == "Adjusted tool completed."


def test_linear_workflow_stops_when_adjustment_is_not_accepted(monkeypatch):
    runner = workflow_module._LinearWorkflow()

    _patch_linear_workflow_until_raster_prepare_validation(monkeypatch)
    monkeypatch.setattr(
        workflow_module,
        "tool_validator_node",
        lambda state: {
            "runtime": {"validators": {"raster_prepare": {"status": "retryable"}}}
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "tool_adjuster_node",
        lambda state: {"status": "planned"},
    )

    state = runner.invoke(AgentState(user_query="Adjustment rejected."))

    assert state.status == "completed"
    assert state.final_answer == (
        "Unable to generate a direct answer for: Adjustment rejected."
    )


def test_get_validation_status_ignores_non_dict_and_non_string_status():
    assert (
        workflow_module._get_validation_status(
            AgentState(
                user_query="Bad validators.",
                runtime={"validators": "invalid"},
            ),
            "raster_prepare",
        )
        is None
    )
    assert (
        workflow_module._get_validation_status(
            AgentState(
                user_query="Bad latest.",
                runtime={"validators": {"latest": "invalid"}},
            ),
            None,
        )
        is None
    )
    assert (
        workflow_module._get_validation_status(
            AgentState(
                user_query="Bad status.",
                runtime={"validators": {"latest": {"status": 1}}},
            ),
            None,
        )
        is None
    )


def test_get_last_tool_call_id_ignores_missing_or_blank_values():
    assert (
        workflow_module._get_last_tool_call_id(AgentState(user_query="No id.")) is None
    )
    assert (
        workflow_module._get_last_tool_call_id(
            AgentState(user_query="Blank id.", runtime={"last_tool_call_id": "  "})
        )
        is None
    )


def _patch_linear_workflow_until_raster_prepare_validation(
    monkeypatch,
    executor_calls=None,
):
    if executor_calls is None:
        executor_calls = []

    monkeypatch.setattr(
        workflow_module,
        "planner_node",
        lambda state: {
            "status": "planned",
            "plan": {"route": "direct_answer", "answer_mode": "direct_answer"},
        },
    )
    monkeypatch.setattr(
        workflow_module,
        "compiler_node",
        lambda state: {
            "tool_calls": [
                {
                    "id": "raster_prepare",
                    "tool_name": "raster_prepare.prepare_raster_inputs",
                    "params": {},
                }
            ],
            "runtime": {"current_tool_index": 0},
        },
    )

    def fake_tool_executor_node(state):
        executor_calls.append(state.runtime.get("current_tool_index"))
        if len(executor_calls) == 1:
            return {
                "runtime": {
                    "last_tool_call_id": "raster_prepare",
                    "current_tool_index": 1,
                }
            }
        return {
            "final_answer": "Adjusted tool completed.",
            "status": "completed",
            "runtime": {"last_tool_call_id": "answer", "current_tool_index": 1},
        }

    monkeypatch.setattr(
        workflow_module,
        "tool_executor_node",
        fake_tool_executor_node,
    )
