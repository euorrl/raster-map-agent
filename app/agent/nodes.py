import json
from pathlib import Path
from typing import Any

from app.registry import resolve_raster_product_config
from app.schemas import AgentState
from app.tools.index_calculation import (
    IndexCalculationRequest,
    calculate_raster_index,
)
from app.tools.raster_prepare import RasterPrepareRequest, prepare_raster_inputs
from app.tools.render_preview import RenderPreviewRequest, render_index_preview
from app.tools.workspace import WorkspaceRequest, create_workspace


def planner_node(state: AgentState) -> dict[str, Any]:
    plan = {
        "product_type": "vegetation_distribution_map",
        "index_name": "NDVI",
        "data_source": "sentinel2",
        "aoi_query": "Chengdu, Sichuan, China",
        "aoi_name": "Chengdu",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 30,
        "recovery_policy": {
            "allow_raster_prepare_retry": True,
            "max_raster_prepare_attempts": 2,
        },
    }
    return {
        "plan": plan,
        "metadata": {"plan": plan},
        "status": "planned",
    }


def registry_node(state: AgentState) -> dict[str, Any]:
    product_config = resolve_raster_product_config(
        state.plan.get("index_name", "NDVI"),
        state.plan.get("data_source", "sentinel2"),
    )
    registry_result = {
        "index_name": product_config.index_name,
        "data_source": product_config.data_source,
        "required_bands": product_config.required_bands,
        "band_roles": product_config.band_roles,
        "index_formula": product_config.index_formula,
    }
    return {
        "plan": registry_result,
        "metadata": {"registry": registry_result},
    }


def workspace_node(state: AgentState) -> dict[str, Any]:
    try:
        result = create_workspace(WorkspaceRequest())
    except Exception as error:
        return {
            "errors": [f"Workspace creation failed: {error}"],
            "status": "failed",
        }

    workspace_result = result.model_dump(mode="json")
    return {
        "workspace": workspace_result,
        "metadata": {"workspace": workspace_result},
    }


def raster_prepare_node(state: AgentState) -> dict[str, Any]:
    workspace_dir = state.workspace.get("workspace_dir")
    if not workspace_dir:
        return {"errors": ["Workspace is missing."], "status": "failed"}

    try:
        result = prepare_raster_inputs(
            RasterPrepareRequest(
                aoi_query=state.plan["aoi_query"],
                index_name=state.plan["index_name"],
                data_source=state.plan["data_source"],
                start_date=state.plan["start_date"],
                end_date=state.plan["end_date"],
                max_cloud_cover=state.plan.get("max_cloud_cover", 30),
                workspace_dir=Path(workspace_dir),
            )
        )
    except Exception as error:
        return {
            "errors": [f"Raster prepare failed: {error}"],
            "status": "failed",
        }

    raster_prepare_result = result.model_dump(mode="json")
    return {
        "tool_results": {"raster_prepare": raster_prepare_result},
        "metadata": {"raster_prepare": raster_prepare_result},
    }


def raster_prepare_validator_node(state: AgentState) -> dict[str, Any]:
    errors = []
    raster_prepare_result = state.tool_results.get("raster_prepare", {})
    required_bands = state.plan.get("required_bands", [])
    band_paths = raster_prepare_result.get("band_paths", {})
    diagnostics = raster_prepare_result.get("diagnostics", {})

    if not required_bands:
        errors.append("Required bands are missing.")

    missing_bands = [band for band in required_bands if band not in band_paths]
    if missing_bands:
        errors.append(f"Band paths are missing for: {', '.join(missing_bands)}.")

    if diagnostics.get("coverage_status") not in {"covered", None}:
        errors.append("Raster prepare coverage is not sufficient.")

    if errors:
        return {"errors": errors, "status": "failed"}

    return {"errors": [], "status": "raster_prepared"}


def product_generation_node(state: AgentState) -> dict[str, Any]:
    workspace_dir = state.workspace.get("workspace_dir")
    if not workspace_dir:
        return {"errors": ["Workspace is missing."], "status": "failed"}

    try:
        index_result_model = calculate_raster_index(
            IndexCalculationRequest(
                workspace_dir=Path(workspace_dir),
                index_name=state.plan["index_name"],
                band_roles=state.plan["band_roles"],
                index_formula=state.plan["index_formula"],
            )
        )
        preview_result_model = render_index_preview(
            RenderPreviewRequest(
                index_name=state.plan["index_name"],
                index_tif_path=Path(index_result_model.index_tif_path),
            )
        )
    except Exception as error:
        return {
            "errors": [f"Product generation failed: {error}"],
            "status": "failed",
        }

    index_result = index_result_model.model_dump(mode="json")
    preview_result = preview_result_model.model_dump(mode="json")
    metadata_result = _export_metadata(
        workspace_dir=Path(workspace_dir),
        state=state,
        index_result=index_result,
        preview_result=preview_result,
    )
    return {
        "tool_results": {
            "index_calculation": index_result,
            "render_preview": preview_result,
            "metadata_export": metadata_result,
        },
        "metadata": {
            "index_calculation": index_result,
            "render_preview": preview_result,
            "metadata_export": metadata_result,
        },
        "status": "product_generated",
    }


def answer_node(state: AgentState) -> dict[str, Any]:
    if state.plan.get("response_mode") == "direct_answer":
        return {
            "final_answer": f"Mock direct answer for: {state.user_query}",
            "status": "completed",
        }

    if state.status == "failed":
        error_text = "; ".join(state.errors) or "Unknown workflow error."
        return {
            "final_answer": f"Mock workflow failed: {error_text}",
            "status": "failed",
        }

    return {
        "final_answer": (
            f"{state.plan.get('index_name')} map generated for "
            f"{state.plan.get('aoi_query')}."
        ),
        "status": "completed",
    }


def _export_metadata(
    workspace_dir: Path,
    state: AgentState,
    index_result: dict[str, Any],
    preview_result: dict[str, Any],
) -> dict[str, str]:
    output_dir = workspace_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "metadata.json"
    metadata = {
        "plan": state.plan,
        "workspace": state.workspace,
        "raster_prepare": state.tool_results.get("raster_prepare", {}),
        "index_calculation": index_result,
        "render_preview": preview_result,
        "warnings": state.warnings,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"metadata_path": str(metadata_path)}
