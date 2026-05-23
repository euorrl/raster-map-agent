"""栅格 AOI 裁剪工具。"""

import json
from pathlib import Path

import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom

from app.tools.raster_prepare.schemas import (
    RasterClipError,
    RasterClipRequest,
    RasterClipResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

GEOJSON_CRS = "EPSG:4326"


def clip_raster_to_aoi(request: RasterClipRequest) -> RasterClipResult:
    """按 AOI GeoJSON 裁剪单个 GeoTIFF。

    Args:
        request: 包含输入 raster、AOI GeoJSON 和输出路径的裁剪请求。

    Returns:
        包含裁剪后 GeoTIFF 路径的结果。
    """

    _ensure_file_exists(request.raster_path, "Input raster")
    _ensure_file_exists(request.boundary_geojson_path, "AOI GeoJSON")

    logger.info(
        "Clipping raster raster_path=%s boundary_geojson_path=%s",
        request.raster_path,
        request.boundary_geojson_path,
    )

    geometries = _load_geojson_geometries(request.boundary_geojson_path)

    with rasterio.open(request.raster_path) as source:
        if source.crs is None:
            raise RasterClipError(f"Input raster has no CRS: {request.raster_path}")

        raster_geometries = _transform_geometries_to_raster_crs(
            geometries,
            str(source.crs),
        )
        clipped_data, clipped_transform = mask(
            source,
            raster_geometries,
            crop=True,
            filled=False,
        )
        clipped_data = clipped_data.astype("float32").filled(-9999.0)
        profile = source.profile.copy()
        profile.update(
            height=clipped_data.shape[1],
            width=clipped_data.shape[2],
            transform=clipped_transform,
            dtype="float32",
            nodata=-9999.0,
        )

    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(request.output_path, "w", **profile) as destination:
        destination.write(clipped_data)

    logger.info("Saved clipped raster path=%s", request.output_path)

    return RasterClipResult(
        source_raster_path=str(request.raster_path),
        boundary_geojson_path=str(request.boundary_geojson_path),
        clipped_raster_path=str(request.output_path),
    )


def _ensure_file_exists(path: Path, label: str) -> None:
    """确认输入文件存在。"""

    if not path.exists():
        raise RasterClipError(f"{label} does not exist: {path}")


def _load_geojson_geometries(path: Path) -> list[dict]:
    """从 GeoJSON 文件中读取 geometry 列表。"""

    try:
        geojson = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RasterClipError(f"Failed to read AOI GeoJSON: {path}") from error

    if geojson.get("type") == "FeatureCollection":
        geometries = [
            feature.get("geometry")
            for feature in geojson.get("features", [])
            if feature.get("geometry")
        ]
    elif geojson.get("type") == "Feature":
        geometries = [geojson["geometry"]]
    else:
        geometries = [geojson]

    if not geometries:
        raise RasterClipError(f"AOI GeoJSON has no geometries: {path}")

    return geometries


def _transform_geometries_to_raster_crs(
    geometries: list[dict],
    raster_crs: str,
) -> list[dict]:
    """把 GeoJSON geometry 从 WGS84 转到输入 raster 的 CRS。"""

    if raster_crs == GEOJSON_CRS:
        return geometries

    return [
        transform_geom(
            GEOJSON_CRS,
            raster_crs,
            geometry,
        )
        for geometry in geometries
    ]
