"""基于尺度的 raster 数据下载工具。"""

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.tools.raster_prepare.schemas import (
    EARTH_SEARCH_BAND_ASSETS,
    RasterDownloadError,
    RasterDownloadRequest,
    RasterDownloadResult,
    RasterScene,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

EARTH_SEARCH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"


def download_raster_bands(request: RasterDownloadRequest) -> RasterDownloadResult:
    """搜索并下载请求中的栅格波段。

    Args:
        request: 栅格数据下载请求。

    Returns:
        下载结果，包含选中的 scene 和各波段本地路径。

    Raises:
        RasterDownloadError: 当没有候选 scene、缺少波段 asset 或下载失败时抛出。
    """

    logger.info(
        "Searching raster data provider=%s collection=%s bbox=%s",
        request.provider,
        request.collection,
        request.bbox,
    )
    scenes = _search_earth_search(request)
    scenes = _filter_scenes_by_cloud_cover(scenes, request.max_cloud_cover)

    if not scenes:
        raise RasterDownloadError(
            "No raster scenes found for the requested parameters."
        )

    selected_scene = _select_scene(scenes)
    band_urls = _extract_band_urls(selected_scene, request.required_bands)

    request.output_dir.mkdir(parents=True, exist_ok=True)
    band_paths: dict[str, str] = {}

    for band, url in band_urls.items():
        output_path = _build_band_output_path(
            request.output_dir,
            selected_scene,
            band,
            url,
        )
        logger.info(
            "Downloading raster band=%s scene=%s",
            band,
            selected_scene.scene_id,
        )
        _download_asset(url, output_path)
        band_paths[band] = str(output_path)

    return RasterDownloadResult(
        selected_scene=selected_scene.scene_id,
        band_paths=band_paths,
        provider=request.provider,
        collection=request.collection,
    )


def _search_earth_search(request: RasterDownloadRequest) -> list[RasterScene]:
    """调用 Earth Search STAC API 搜索候选 scene。"""

    payload = {
        "collections": [request.collection],
        "bbox": request.bbox,
        "datetime": _build_stac_datetime_range(request.start_date, request.end_date),
        "limit": request.limit,
    }

    response = _post_json(EARTH_SEARCH_SEARCH_URL, payload)
    features = response.get("features", [])

    return [_parse_stac_item(feature) for feature in features]


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """向指定 URL 发送 JSON POST 请求并解析 JSON 响应。"""

    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RasterDownloadError(
            f"Failed to query STAC API: {url} " f"(HTTP {error.code}: {error_body})"
        ) from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RasterDownloadError(f"Failed to query STAC API: {url}") from error


def _build_stac_datetime_range(start_date: str, end_date: str) -> str:
    """将简单日期范围转换为 STAC API 需要的 RFC3339 时间范围。"""

    start = _parse_date(start_date)
    end = _parse_date(end_date)

    return f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"


def _parse_date(value: str) -> date:
    """解析 ``YYYY-MM-DD`` 日期字符串。"""

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise RasterDownloadError(f"Invalid date format: {value}") from error


def _parse_stac_item(item: dict[str, Any]) -> RasterScene:
    """将原始 STAC Item 转换为内部 scene 模型。"""

    properties = item.get("properties", {})
    assets = {
        asset_key: asset["href"]
        for asset_key, asset in item.get("assets", {}).items()
        if "href" in asset
    }

    return RasterScene(
        scene_id=item["id"],
        datetime=properties.get("datetime"),
        cloud_cover=properties.get("eo:cloud_cover"),
        assets=assets,
    )


def _select_scene(scenes: list[RasterScene]) -> RasterScene:
    """从候选 scene 中选择云量最低的一景。"""

    return sorted(
        scenes,
        key=lambda scene: (
            scene.cloud_cover is None,
            scene.cloud_cover if scene.cloud_cover is not None else 101,
        ),
    )[0]


def _filter_scenes_by_cloud_cover(
    scenes: list[RasterScene],
    max_cloud_cover: float,
) -> list[RasterScene]:
    """按最大云量阈值过滤候选 scene。"""

    return [
        scene
        for scene in scenes
        if scene.cloud_cover is not None and scene.cloud_cover < max_cloud_cover
    ]


def _extract_band_urls(scene: RasterScene, required_bands: list[str]) -> dict[str, str]:
    """从 scene assets 中提取请求波段对应的下载 URL。"""

    band_urls = {}

    for band in required_bands:
        asset_key = EARTH_SEARCH_BAND_ASSETS[band]
        asset_url = scene.assets.get(asset_key)

        if not asset_url:
            raise RasterDownloadError(
                f"Scene {scene.scene_id} is missing asset for band {band}."
            )

        band_urls[band] = asset_url

    return band_urls


def _build_band_output_path(
    output_dir: Path,
    scene: RasterScene,
    band: str,
    url: str,
) -> Path:
    """根据 scene、波段和源 URL 构造本地输出路径。"""

    suffix = Path(urlparse(url).path).suffix or ".tif"
    return output_dir / f"{scene.scene_id}_{band}{suffix}"


def _download_asset(url: str, output_path: Path) -> None:
    """下载单个栅格 asset 到本地路径。"""

    try:
        with urlopen(url, timeout=120) as response:
            with output_path.open("wb") as file:
                shutil.copyfileobj(response, file)
    except (OSError, URLError) as error:
        raise RasterDownloadError(f"Failed to download raster asset: {url}") from error
