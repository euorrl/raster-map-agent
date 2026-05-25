"""栅格按波段合并工具。"""

from contextlib import ExitStack
from pathlib import Path
import re

import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT

from app.tools.raster_prepare.schemas import (
    RasterMosaicError,
    RasterMosaicRequest,
    RasterMosaicResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

BAND_NAME_PATTERN = re.compile(r"_(B\d{2}[A-Z]?)$", re.IGNORECASE)


def mosaic_rasters_by_band(request: RasterMosaicRequest) -> RasterMosaicResult:
    """扫描输入目录中的 GeoTIFF，并按 band 输出 first mosaic。"""

    if not request.input_dir.exists():
        raise RasterMosaicError(
            f"Input raster directory does not exist: {request.input_dir}"
        )
    if not request.input_dir.is_dir():
        raise RasterMosaicError(
            f"Input raster path is not a directory: {request.input_dir}"
        )

    raster_paths = _find_raster_paths(request.input_dir)
    if not raster_paths:
        raise RasterMosaicError(f"No GeoTIFF files found in: {request.input_dir}")

    grouped_paths = _group_raster_paths_by_band(raster_paths)
    if not grouped_paths:
        raise RasterMosaicError(
            f"No band names could be parsed from GeoTIFF files in: {request.input_dir}"
        )

    logger.info(
        "Mosaicking raster directory input_dir=%s output_dir=%s bands=%s",
        request.input_dir,
        request.output_dir,
        sorted(grouped_paths),
    )

    request.output_dir.mkdir(parents=True, exist_ok=True)
    band_paths = {}
    for band, band_raster_paths in sorted(grouped_paths.items()):
        output_path = request.output_dir / f"mosaic_{band}.tif"
        _mosaic_single_band(
            raster_paths=band_raster_paths,
            output_path=output_path,
        )
        band_paths[band] = str(output_path)

    return RasterMosaicResult(band_paths=band_paths)


def _find_raster_paths(input_dir: Path) -> list[Path]:
    """查找目录中的 GeoTIFF 文件。"""

    return sorted([*input_dir.glob("*.tif"), *input_dir.glob("*.tiff")])


def _group_raster_paths_by_band(raster_paths: list[Path]) -> dict[str, list[Path]]:
    """根据文件名中的 band 后缀给 GeoTIFF 分组。"""

    grouped_paths: dict[str, list[Path]] = {}
    for raster_path in raster_paths:
        band = _parse_band_name(raster_path)
        if band is None:
            continue

        grouped_paths.setdefault(band, []).append(raster_path)

    return grouped_paths


def _parse_band_name(raster_path: Path) -> str | None:
    """从文件名末尾解析 Sentinel 风格 band 名称。"""

    match = BAND_NAME_PATTERN.search(raster_path.stem)
    if match is None:
        return None

    return match.group(1).upper()


def _mosaic_single_band(raster_paths: list[Path], output_path: Path) -> None:
    """把同一 band 的多个 GeoTIFF 用 first 策略合并为一张图。"""

    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(path)) for path in raster_paths]
        target_crs = datasets[0].crs
        if target_crs is None:
            raise RasterMosaicError(f"Input raster has no CRS: {raster_paths[0]}")

        mosaic_sources = _build_mosaic_sources(
            datasets=datasets,
            target_crs=target_crs,
            stack=stack,
        )
        mosaic_data, mosaic_transform = merge(mosaic_sources, method="first")
        profile = datasets[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=mosaic_data.shape[1],
            width=mosaic_data.shape[2],
            transform=mosaic_transform,
            count=mosaic_data.shape[0],
            dtype=mosaic_data.dtype,
            crs=target_crs,
        )

    with rasterio.open(output_path, "w", **profile) as destination:
        destination.write(mosaic_data)

    logger.info(
        "Saved mosaic raster band=%s input_count=%s path=%s",
        _parse_band_name(output_path) or output_path.stem,
        len(raster_paths),
        output_path,
    )


def _build_mosaic_sources(datasets, target_crs, stack: ExitStack):
    """把不同 CRS 的输入包装为临时 VRT，使 merge 可以统一到目标 CRS。"""

    mosaic_sources = []
    for dataset in datasets:
        if dataset.crs is None:
            raise RasterMosaicError(f"Input raster has no CRS: {dataset.name}")

        if dataset.crs == target_crs:
            mosaic_sources.append(dataset)
            continue

        mosaic_sources.append(
            stack.enter_context(
                WarpedVRT(
                    dataset,
                    crs=target_crs,
                    resampling=Resampling.nearest,
                )
            )
        )

    return mosaic_sources
