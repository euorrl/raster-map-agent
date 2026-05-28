"""栅格数据准备 pipeline。"""

from pathlib import Path
import shutil

from app.registry import resolve_raster_product_config
from app.tools.raster_prepare import (
    build_raster_scene_plan,
    clip_raster_to_aoi,
    download_raster_assets,
    mosaic_rasters_by_band,
    resolve_administrative_aoi,
)
from app.tools.raster_prepare.schemas import (
    AOIRequest,
    MOSAIC_RASTER_DIRNAME,
    OUTPUT_DIRNAME,
    RASTER_DIRNAME,
    RasterClipRequest,
    RasterDownloadRequest,
    RasterMosaicRequest,
    RasterPrepareRequest,
    RasterPrepareResult,
    RasterScenePlanRequest,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def prepare_raster_inputs(request: RasterPrepareRequest) -> RasterPrepareResult:
    """运行 AOI、scene plan、download、mosaic、clip 的完整数据准备流程。"""

    workspace_dir = request.workspace_dir
    workspace_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Preparing raster inputs workspace_dir=%s", workspace_dir)
    product_config = resolve_raster_product_config(
        request.index_name,
        request.data_source,
    )

    aoi = resolve_administrative_aoi(
        AOIRequest(
            query=request.aoi_query,
            workspace_dir=workspace_dir,
            limit=request.aoi_limit,
        )
    )
    scene_plan = build_raster_scene_plan(
        RasterScenePlanRequest(
            bbox=aoi.bbox,
            boundary_geojson_path=Path(aoi.boundary_geojson_path),
            start_date=request.start_date,
            end_date=request.end_date,
            max_cloud_cover=request.max_cloud_cover,
            required_bands=product_config.required_bands,
            data_source=request.data_source,
            limit=request.scene_limit,
            max_selected_scenes=request.max_selected_scenes,
            contribution_tolerance=request.contribution_tolerance,
            min_scene_overlap_ratio=request.min_scene_overlap_ratio,
            min_coverage_ratio=request.min_coverage_ratio,
        )
    )
    if not _scene_plan_is_acceptable(scene_plan.diagnostics):
        output_dir = workspace_dir / OUTPUT_DIRNAME
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Skipping raster download because scene coverage is not acceptable "
            "coverage_status=%s coverage_ratio=%s min_coverage_ratio=%s",
            scene_plan.diagnostics.coverage_status,
            scene_plan.diagnostics.coverage_ratio,
            scene_plan.diagnostics.min_coverage_ratio,
        )
        return RasterPrepareResult(
            workspace_dir=str(workspace_dir),
            output_dir=str(output_dir),
            boundary_geojson_path=aoi.boundary_geojson_path,
            index_name=product_config.index_name,
            data_source=product_config.data_source,
            provider=scene_plan.provider,
            collection=scene_plan.collection,
            required_bands=product_config.required_bands,
            band_roles=product_config.band_roles,
            index_formula=product_config.index_formula,
            band_paths={},
            scene_ids=scene_plan.scene_ids,
            diagnostics=scene_plan.diagnostics,
        )

    download_raster_assets(
        RasterDownloadRequest(
            plan=scene_plan,
            workspace_dir=workspace_dir,
        )
    )
    mosaic = mosaic_rasters_by_band(
        RasterMosaicRequest(
            input_dir=workspace_dir / RASTER_DIRNAME,
            output_dir=workspace_dir / MOSAIC_RASTER_DIRNAME,
        )
    )
    band_paths = _clip_mosaic_bands(
        mosaic_band_paths=mosaic.band_paths,
        boundary_geojson_path=Path(aoi.boundary_geojson_path),
        workspace_dir=workspace_dir,
    )
    output_dir = workspace_dir / OUTPUT_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)

    _remove_intermediate_dirs(
        workspace_dir=workspace_dir,
        dirnames=[RASTER_DIRNAME, MOSAIC_RASTER_DIRNAME],
    )

    return RasterPrepareResult(
        workspace_dir=str(workspace_dir),
        output_dir=str(output_dir),
        boundary_geojson_path=aoi.boundary_geojson_path,
        index_name=product_config.index_name,
        data_source=product_config.data_source,
        provider=scene_plan.provider,
        collection=scene_plan.collection,
        required_bands=product_config.required_bands,
        band_roles=product_config.band_roles,
        index_formula=product_config.index_formula,
        band_paths=band_paths,
        scene_ids=scene_plan.scene_ids,
        diagnostics=scene_plan.diagnostics,
    )


def _clip_mosaic_bands(
    mosaic_band_paths: dict[str, str],
    boundary_geojson_path: Path,
    workspace_dir: Path,
) -> dict[str, str]:
    """把每个 band 的 mosaic tif 裁剪到 AOI。"""

    band_paths = {}
    for band, raster_path in sorted(mosaic_band_paths.items()):
        clip_result = clip_raster_to_aoi(
            RasterClipRequest(
                raster_path=Path(raster_path),
                boundary_geojson_path=boundary_geojson_path,
                workspace_dir=workspace_dir,
                output_filename=f"{band}_clipped.tif",
            )
        )
        band_paths[band] = clip_result.clipped_raster_path

    return band_paths


def _scene_plan_is_acceptable(diagnostics) -> bool:
    """判断 scene plan 覆盖率是否足够进入下载阶段。"""

    return (
        diagnostics.coverage_status == "covered"
        or diagnostics.coverage_ratio >= diagnostics.min_coverage_ratio
    )


def _remove_intermediate_dirs(workspace_dir: Path, dirnames: list[str]) -> None:
    """删除本次 workspace 内的中间目录。"""

    resolved_workspace = workspace_dir.resolve()
    for dirname in dirnames:
        target_dir = (workspace_dir / dirname).resolve()
        if not _is_relative_to(target_dir, resolved_workspace):
            raise RuntimeError(f"Refuse to delete path outside workspace: {target_dir}")
        if target_dir.exists():
            shutil.rmtree(target_dir)
            logger.info("Removed intermediate directory path=%s", target_dir)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path.is_relative_to。"""

    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True
