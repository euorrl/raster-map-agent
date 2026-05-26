from typing import Any

from app.registry import get_index_config
from app.schemas import AgentState


def planner_node(state: AgentState) -> dict[str, Any]:
    plan = {
        "product_type": "vegetation_distribution_map",
        "index_name": "NDVI",
        "data_source": "sentinel2",
        "aoi_query": "Milan",
        "aoi_name": "Milan",
    }
    return {
        "plan": plan,
        "metadata": {"plan": plan},
        "status": "planned",
    }


def registry_node(state: AgentState) -> dict[str, Any]:
    index_config = get_index_config(state.plan.get("index_name", "NDVI"))
    registry_result = {
        "required_bands": index_config.required_bands,
        "index_formula": index_config.index_formula,
    }
    return {
        "plan": registry_result,
        "metadata": {"registry": registry_result},
    }


def workflow_router_node(state: AgentState) -> dict[str, Any]:
    workflow_result = {"workflow_type": "single_index_map"}
    return {
        "plan": workflow_result,
        "metadata": {"workflow": workflow_result},
    }


def aoi_node(state: AgentState) -> dict[str, Any]:
    aoi_result = {
        "aoi_name": state.plan.get("aoi_name", "Milan"),
        "bbox": [9.04, 45.35, 9.32, 45.56],
    }
    return {
        "tool_results": {"aoi": aoi_result},
        "metadata": {"aoi": aoi_result},
        "warnings": ["Using mock AOI bounding box for Milan."],
    }


def download_node(state: AgentState) -> dict[str, Any]:
    download_result = {
        "selected_scene": "mock_sentinel2_scene",
        "band_paths": {
            "B04": "data/mock_B04.tif",
            "B08": "data/mock_B08.tif",
        },
    }
    return {
        "tool_results": {"download": download_result},
        "metadata": {"download": download_result},
        "warnings": ["Using mock Sentinel-2 band paths."],
    }


def validator_node(state: AgentState) -> dict[str, Any]:
    errors = []
    aoi_result = state.tool_results.get("aoi", {})
    download_result = state.tool_results.get("download", {})
    required_bands = state.plan.get("required_bands", [])
    band_paths = download_result.get("band_paths", {})

    if not aoi_result.get("aoi_name") or not aoi_result.get("bbox"):
        errors.append("AOI is missing.")

    if not required_bands:
        errors.append("Required bands are missing.")

    missing_bands = [band for band in required_bands if band not in band_paths]
    if missing_bands:
        errors.append(f"Band paths are missing for: {', '.join(missing_bands)}.")

    if errors:
        return {"errors": errors, "status": "failed"}

    return {"errors": [], "status": "validated"}


def process_node(state: AgentState) -> dict[str, Any]:
    result = {"result_tif_path": "data/mock/output/mock_ndvi.tif"}
    return {
        "tool_results": {"index_calculation": result},
        "metadata": {"index_calculation": result},
    }


def render_node(state: AgentState) -> dict[str, Any]:
    result = {"preview_path": "data/mock/output/mock_preview.png"}
    return {
        "tool_results": {"render_preview": result},
        "metadata": {"render_preview": result},
    }


def metadata_node(state: AgentState) -> dict[str, Any]:
    metadata_result = {"metadata_path": "data/mock/output/mock_metadata.json"}
    return {
        "tool_results": {"metadata": metadata_result},
        "metadata": {"metadata": metadata_result},
    }


def answer_node(state: AgentState) -> dict[str, Any]:
    if state.status == "failed":
        error_text = "; ".join(state.errors) or "Unknown workflow error."
        return {
            "final_answer": f"Mock workflow failed: {error_text}",
            "status": "failed",
        }

    return {
        "final_answer": (
            "Mock "
            f"{state.plan.get('index_name')} vegetation map generated for "
            f"{state.tool_results.get('aoi', {}).get('aoi_name')}."
        ),
        "status": "completed",
    }
