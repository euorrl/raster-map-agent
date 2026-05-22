from typing import Any

from app.schemas.state import AgentState


INDEX_REGISTRY = {
    "NDVI": {
        "required_bands": ["B04", "B08"],
        "index_formula": "(nir - red) / (nir + red)",
    }
}


def planner_node(state: AgentState) -> dict[str, Any]:
    return {
        "product_type": "vegetation_distribution_map",
        "index": "NDVI",
        "data_source": "sentinel2",
        "aoi_name": "Milan",
    }


def registry_node(state: AgentState) -> dict[str, Any]:
    index_config = INDEX_REGISTRY[state.index or "NDVI"]
    return index_config


def workflow_router_node(state: AgentState) -> dict[str, Any]:
    return {"workflow_type": "single_index_map"}


def aoi_node(state: AgentState) -> dict[str, Any]:
    return {
        "aoi_name": state.aoi_name or "Milan",
        "bbox": [9.04, 45.35, 9.32, 45.56],
        "warnings": ["Using mock AOI bounding box for Milan."],
    }


def download_node(state: AgentState) -> dict[str, Any]:
    return {
        "selected_scene": "mock_sentinel2_scene",
        "band_paths": {
            "B04": "data/mock_B04.tif",
            "B08": "data/mock_B08.tif",
        },
        "warnings": ["Using mock Sentinel-2 band paths."],
    }


def validator_node(state: AgentState) -> dict[str, Any]:
    errors = []

    if not state.aoi_name or not state.bbox:
        errors.append("AOI is missing.")

    if not state.required_bands:
        errors.append("Required bands are missing.")

    missing_bands = [
        band for band in state.required_bands if band not in state.band_paths
    ]
    if missing_bands:
        errors.append(f"Band paths are missing for: {', '.join(missing_bands)}.")

    if errors:
        return {"errors": errors, "status": "failed"}

    return {"errors": [], "status": "validated"}


def process_node(state: AgentState) -> dict[str, Any]:
    return {"result_tif_path": "outputs/mock_ndvi.tif"}


def render_node(state: AgentState) -> dict[str, Any]:
    return {"preview_path": "outputs/mock_preview.png"}


def metadata_node(state: AgentState) -> dict[str, Any]:
    metadata = {
        "product_type": state.product_type,
        "index": state.index,
        "aoi_name": state.aoi_name,
        "data_source": state.data_source,
    }
    return {
        "metadata": metadata,
        "metadata_path": "outputs/mock_metadata.json",
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
            f"Mock {state.index} vegetation map generated for {state.aoi_name}."
        ),
        "status": "completed",
    }
