from app.tools.raster_prepare.schemas import (
    AOIRequest,
    AOIResult,
    RasterClipError,
    RasterClipRequest,
    RasterClipResult,
    RasterDownloadAsset,
    RasterDownloadError,
    RasterDownloadRequest,
    RasterDownloadResult,
    RasterMosaicError,
    RasterMosaicRequest,
    RasterMosaicResult,
    RasterPrepareRequest,
    RasterPrepareResult,
    RasterScene,
    RasterSceneCandidateStore,
    RasterScenePlanDiagnostics,
    RasterScenePlanRequest,
    RasterScenePlanResult,
)

__all__ = [
    "AOIRequest",
    "AOIResult",
    "RasterClipError",
    "RasterClipRequest",
    "RasterClipResult",
    "RasterDownloadAsset",
    "RasterDownloadError",
    "RasterDownloadRequest",
    "RasterDownloadResult",
    "RasterMosaicError",
    "RasterMosaicRequest",
    "RasterMosaicResult",
    "RasterPrepareRequest",
    "RasterPrepareResult",
    "RasterScene",
    "RasterSceneCandidateStore",
    "RasterScenePlanDiagnostics",
    "RasterScenePlanRequest",
    "RasterScenePlanResult",
    "build_raster_scene_plan",
    "build_raster_scene_plan_from_candidates",
    "clip_raster_to_aoi",
    "download_raster_assets",
    "mosaic_rasters_by_band",
    "prepare_raster_inputs",
    "resolve_administrative_aoi",
    "update_raster_scene_candidates",
]


def resolve_administrative_aoi(request):
    """Lazy wrapper for AOI resolution."""

    from app.tools.raster_prepare.aoi import (
        resolve_administrative_aoi as _resolve_administrative_aoi,
    )

    return _resolve_administrative_aoi(request)


def clip_raster_to_aoi(request):
    """Lazy wrapper for raster clipping."""

    from app.tools.raster_prepare.clip import clip_raster_to_aoi as _clip_raster_to_aoi

    return _clip_raster_to_aoi(request)


def download_raster_assets(request):
    """Lazy wrapper for raster asset downloads."""

    from app.tools.raster_prepare.download import (
        download_raster_assets as _download_raster_assets,
    )

    return _download_raster_assets(request)


def mosaic_rasters_by_band(request):
    """Lazy wrapper for raster mosaicking."""

    from app.tools.raster_prepare.mosaic import (
        mosaic_rasters_by_band as _mosaic_rasters_by_band,
    )

    return _mosaic_rasters_by_band(request)


def prepare_raster_inputs(request):
    """Lazy wrapper for the raster prepare pipeline."""

    from app.tools.raster_prepare.prepare import (
        prepare_raster_inputs as _prepare_raster_inputs,
    )

    return _prepare_raster_inputs(request)


def build_raster_scene_plan(*args, **kwargs):
    """Lazy wrapper for scene planning."""

    from app.tools.raster_prepare.scene_plan import (
        build_raster_scene_plan as _build_raster_scene_plan,
    )

    return _build_raster_scene_plan(*args, **kwargs)


def build_raster_scene_plan_from_candidates(*args, **kwargs):
    """Lazy wrapper for candidate-store scene planning."""

    from app.tools.raster_prepare.scene_plan import (
        build_raster_scene_plan_from_candidates as _build_from_candidates,
    )

    return _build_from_candidates(*args, **kwargs)


def update_raster_scene_candidates(*args, **kwargs):
    """Lazy wrapper for scene candidate updates."""

    from app.tools.raster_prepare.scene_plan import (
        update_raster_scene_candidates as _update_raster_scene_candidates,
    )

    return _update_raster_scene_candidates(*args, **kwargs)
