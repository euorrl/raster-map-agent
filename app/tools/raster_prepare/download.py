"""raster 数据下载工具。"""

import shutil
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from app.tools.raster_prepare.schemas import (
    RasterDownloadAsset,
    RasterDownloadError,
    RasterDownloadRequest,
    RasterDownloadResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def download_raster_assets(request: RasterDownloadRequest) -> RasterDownloadResult:
    """根据下载计划下载栅格 asset。

    Args:
        request: 包含下载计划和任务根目录的 asset 下载请求。

    Returns:
        下载结果，包含各波段本地路径列表。

    Raises:
        RasterDownloadError: 当 asset 下载失败时抛出。
    """

    request.output_dir.mkdir(parents=True, exist_ok=True)
    band_paths: dict[str, list[str]] = {
        band: [] for band in _planned_bands(request.plan.assets)
    }

    for asset in request.plan.assets:
        output_path = _build_band_output_path(request.output_dir, asset)
        logger.info(
            "Downloading raster band=%s scene=%s",
            asset.band,
            asset.scene_id,
        )
        _download_asset(asset.url, output_path)
        band_paths[asset.band].append(str(output_path))

    return RasterDownloadResult(
        scene_ids=request.plan.scene_ids,
        band_paths=band_paths,
        data_source=request.plan.data_source,
        provider=request.plan.provider,
        collection=request.plan.collection,
    )


def _planned_bands(assets: list[RasterDownloadAsset]) -> list[str]:
    """按首次出现顺序提取 plan 中的 band 名称。"""

    bands = []
    seen_bands = set()

    for asset in assets:
        if asset.band in seen_bands:
            continue

        seen_bands.add(asset.band)
        bands.append(asset.band)

    return bands


def _build_band_output_path(
    output_dir: Path,
    asset: RasterDownloadAsset,
) -> Path:
    """根据 scene、波段和源 URL 构造本地输出路径。"""

    suffix = Path(urlparse(asset.url).path).suffix or ".tif"
    return output_dir / f"{asset.scene_id}_{asset.band}{suffix}"


def _download_asset(url: str, output_path: Path) -> None:
    """下载单个栅格 asset 到本地路径。"""

    try:
        with urlopen(url, timeout=120) as response:
            with output_path.open("wb") as file:
                shutil.copyfileobj(response, file)
    except (OSError, URLError) as error:
        raise RasterDownloadError(f"Failed to download raster asset: {url}") from error
