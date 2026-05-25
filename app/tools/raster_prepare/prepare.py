"""栅格数据准备 pipeline。"""

from pathlib import Path
import shutil
from uuid import uuid4

from app.tools.raster_prepare.aoi import resolve_administrative_aoi
from app.tools.raster_prepare.clip import clip_raster_to_aoi
from app.tools.raster_prepare.download import download_raster_assets
from app.tools.raster_prepare.mosaic import mosaic_rasters_by_band
from app.tools.raster_prepare.scene_plan import build_raster_scene_plan
from app.tools.raster_prepare.schemas import (
    AOIRequest,
    MOSAIC_RASTER_DIRNAME,
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

    workspace_dir = _create_workspace_dir(request.root_dir)
    logger.info("Preparing raster inputs workspace_dir=%s", workspace_dir)

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
            required_bands=request.required_bands,
            data_source=request.data_source,
            limit=request.scene_limit,
            max_selected_scenes=request.max_selected_scenes,
            contribution_tolerance=request.contribution_tolerance,
            min_scene_overlap_ratio=request.min_scene_overlap_ratio,
            min_coverage_ratio=request.min_coverage_ratio,
        )
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

    _remove_intermediate_dirs(
        workspace_dir=workspace_dir,
        dirnames=[RASTER_DIRNAME, MOSAIC_RASTER_DIRNAME],
    )

    return RasterPrepareResult(
        workspace_dir=str(workspace_dir),
        boundary_geojson_path=aoi.boundary_geojson_path,
        band_paths=band_paths,
        scene_ids=scene_plan.scene_ids,
        diagnostics=scene_plan.diagnostics,
    )


def _create_workspace_dir(root_dir: Path) -> Path:
    """在 root_dir 下创建一次运行专用的 UUID workspace。"""

    root_dir.mkdir(parents=True, exist_ok=True)

    while True:
        workspace_dir = root_dir / uuid4().hex
        try:
            workspace_dir.mkdir()
        except FileExistsError:
            continue

        return workspace_dir


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
