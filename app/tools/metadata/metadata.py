import json
from pathlib import Path
from typing import Any

from app.tools.metadata.schemas import (
    MetadataExportError,
    MetadataExportRequest,
    MetadataExportResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def export_metadata(request: MetadataExportRequest) -> MetadataExportResult:
    """Export compact product metadata for user-facing answers."""

    logger.info("Exporting metadata path=%s", request.output_path)
    product_info = build_product_info(request.workflow_state)
    payload = _build_metadata_payload(product_info)

    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.output_path.write_text(
            json.dumps(
                payload,
                default=_json_default,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError) as error:
        raise MetadataExportError(
            f"Failed to export metadata: {request.output_path}"
        ) from error

    logger.info("Exported metadata path=%s", request.output_path)
    return MetadataExportResult(
        metadata_path=str(request.output_path),
        product_info=product_info,
    )


def build_product_info(workflow_state: dict[str, Any]) -> dict[str, Any]:
    """Build a compact product summary from an AgentState snapshot."""

    plan = _as_dict(workflow_state.get("plan"))
    runtime = _as_dict(workflow_state.get("runtime"))
    tool_results = _as_dict(workflow_state.get("tool_results"))
    registry = _as_dict(runtime.get("registry"))
    raster_product = _as_dict(registry.get("raster_product"))
    raster_prepare = _as_dict(tool_results.get("raster_prepare"))
    validation = _as_dict(_as_dict(runtime.get("validators")).get("raster_prepare"))
    diagnostics = _as_dict(raster_prepare.get("diagnostics"))
    data_source = (
        raster_prepare.get("data_source")
        or raster_product.get("data_source")
        or plan.get("data_source")
    )
    product_raster_path = _find_product_raster_path(tool_results)
    profile_raster_path = product_raster_path or _find_first_band_path(raster_prepare)
    raster_profile = _read_raster_profile(profile_raster_path)
    index_name = (
        raster_prepare.get("index_name")
        or raster_product.get("index_name")
        or plan.get("index_name")
    )
    product_name = (
        raster_prepare.get("product_name")
        or raster_product.get("product_name")
        or plan.get("product_name")
        or index_name
        or plan.get("map_type")
    )
    product_type = (
        raster_prepare.get("product_type")
        or raster_product.get("product_type")
        or plan.get("product_type")
        or plan.get("map_type")
        or ("index" if index_name else None)
    )
    product_method = _build_product_method(raster_prepare, raster_product, plan)

    product_info = {
        "product": {
            "type": product_type,
            "name": product_name,
            "family": "raster",
            "method": product_method,
        },
        "area": {
            "aoi_query": plan.get("aoi_query"),
        },
        "time_range": {
            "start_date": plan.get("start_date"),
            "end_date": plan.get("end_date"),
            "max_cloud_cover": plan.get("max_cloud_cover"),
        },
        "source": {
            "data_source": data_source,
            "provider": (
                raster_prepare.get("provider") or raster_product.get("provider")
            ),
        },
        "spatial": raster_profile,
        "quality": {
            "raster_prepare_validation_status": validation.get("status"),
            "coverage_status": diagnostics.get("coverage_status"),
            "coverage_ratio": diagnostics.get("coverage_ratio"),
            "min_coverage_ratio": diagnostics.get("min_coverage_ratio"),
            "selected_scene_count": diagnostics.get("selected_scene_count"),
        },
        "warnings": list(workflow_state.get("warnings", [])),
    }
    return _drop_empty(product_info)


def _build_product_method(
    raster_prepare: dict[str, Any],
    raster_product: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    formula = raster_prepare.get("index_formula") or raster_product.get(
        "index_formula"
    )
    method_name = (
        raster_prepare.get("method")
        or raster_product.get("method")
        or plan.get("method")
        or ("index_formula" if formula else None)
    )
    return {
        "name": method_name,
        "formula": formula,
    }


def _find_product_raster_path(tool_results: dict[str, Any]) -> str | None:
    path_keys = (
        "product_raster_path",
        "output_raster_path",
        "raster_path",
        "index_tif_path",
    )
    for result in tool_results.values():
        result_dict = _as_dict(result)
        for key in path_keys:
            path_value = result_dict.get(key)
            if _is_tif_path(path_value):
                return path_value

    return None


def _find_first_band_path(raster_prepare: dict[str, Any]) -> str | None:
    band_paths = raster_prepare.get("band_paths")
    if not isinstance(band_paths, dict):
        return None

    for band in sorted(band_paths):
        path_value = band_paths[band]
        if _is_tif_path(path_value):
            return path_value

    return None


def _build_metadata_payload(product_info: dict[str, Any]) -> dict[str, Any]:
    return product_info


def _read_raster_profile(path_value: Any) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value:
        return {}

    path = Path(path_value)
    if not path.exists():
        return {}

    try:
        import rasterio
    except ModuleNotFoundError:
        return {}

    try:
        with rasterio.open(path) as dataset:
            resolution = dataset.res
            crs_unit = _get_crs_unit(dataset.crs)
            resolution_info = None
            resolution_meters = None
            if resolution:
                x_resolution = abs(resolution[0])
                y_resolution = abs(resolution[1])
                resolution_info = {
                    "x": x_resolution,
                    "y": y_resolution,
                    "unit": crs_unit,
                }
                if (
                    dataset.crs
                    and dataset.crs.is_projected
                    and x_resolution == y_resolution
                    and crs_unit in {"metre", "meter", "metres", "meters"}
                ):
                    resolution_meters = x_resolution

            bounds = dataset.bounds
            return {
                "crs": dataset.crs.to_string() if dataset.crs else None,
                "resolution": resolution_info,
                "resolution_meters": resolution_meters,
                "width": dataset.width,
                "height": dataset.height,
                "bounds": {
                    "left": bounds.left,
                    "bottom": bounds.bottom,
                    "right": bounds.right,
                    "top": bounds.top,
                },
            }
    except OSError:
        return {}


def _get_crs_unit(crs: Any) -> str | None:
    if not crs:
        return None
    if crs.is_geographic:
        return "degree"

    return getattr(crs, "linear_units", None)


def _is_tif_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False

    return Path(value).suffix.lower() in {".tif", ".tiff"}


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: _drop_empty(item)
            for key, item in value.items()
            if item is not None and item != "" and item != []
        }
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != {} and item != []
        }

    if isinstance(value, list):
        return [_drop_empty(item) for item in value if item is not None]

    return value


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    return {}


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if isinstance(value, set):
        return sorted(value)

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
