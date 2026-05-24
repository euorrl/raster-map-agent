"""栅格 scene 下载计划构建。"""

import json
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.tools.raster_prepare.schemas import (
    DEFAULT_RASTER_DATA_SOURCE,
    RasterDownloadAsset,
    RasterDownloadError,
    RasterScene,
    RasterSceneCandidateGroup,
    RasterSceneCandidateStore,
    RasterScenePlanResult,
    RasterScenePlanRequest,
    get_raster_data_source_config,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

EARTH_SEARCH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"


def build_raster_scene_plan(
    request: RasterScenePlanRequest,
    store: RasterSceneCandidateStore | None = None,
) -> RasterScenePlanResult:
    """更新候选池，并基于候选池构建待下载 scene asset 清单。

    如果传入 ``store``，函数会原地更新它，因此多次调用可以累积多个
    时间窗口或分页查询的候选 scenes。
    """

    if store is None:
        store = RasterSceneCandidateStore()

    update_raster_scene_candidates(request, store)

    return build_raster_scene_plan_from_candidates(
        store=store,
        required_bands=request.required_bands,
        selected_scenes_per_group=request.selected_scenes_per_group,
        data_source=request.data_source,
    )


def update_raster_scene_candidates(
    request: RasterScenePlanRequest,
    store: RasterSceneCandidateStore,
) -> None:
    """查询当前请求的 scene metadata，并合并进候选池。"""

    logger.info(
        "Updating raster scene candidates data_source=%s bbox=%s",
        request.data_source,
        request.bbox,
    )
    scenes = _search_earth_search(request)
    scenes = _deduplicate_scenes_by_id(scenes)
    scenes = _filter_scenes_by_cloud_cover(scenes, request.max_cloud_cover)

    for scene in scenes:
        group_id = _scene_group_id(scene)
        group = store.groups.setdefault(
            group_id,
            RasterSceneCandidateGroup(group_id=group_id),
        )

        if any(candidate.scene_id == scene.scene_id for candidate in group.candidates):
            continue

        group.candidates.append(scene)
        group.candidates = _sort_scenes_by_cloud_cover(group.candidates)
        group.candidates = group.candidates[: request.max_candidate_scenes_per_group]


def build_raster_scene_plan_from_candidates(
    store: RasterSceneCandidateStore,
    required_bands: list[str],
    selected_scenes_per_group: int,
    data_source: str = DEFAULT_RASTER_DATA_SOURCE,
) -> RasterScenePlanResult:
    """从候选池中选择每组云量最低的 scenes，并生成下载计划。"""

    config = get_raster_data_source_config(data_source)
    selected_scenes = []

    for group in store.groups.values():
        selected_scenes.extend(group.candidates[:selected_scenes_per_group])

    if not selected_scenes:
        raise RasterDownloadError(
            "No raster scenes found for the requested parameters."
        )

    assets = []
    for scene in selected_scenes:
        band_urls = _extract_band_urls(scene, required_bands, config.band_assets)
        for band, url in band_urls.items():
            assets.append(
                RasterDownloadAsset(
                    scene_id=scene.scene_id,
                    band=band,
                    url=url,
                )
            )

    return RasterScenePlanResult(
        scene_ids=[scene.scene_id for scene in selected_scenes],
        assets=assets,
        data_source=config.data_source,
        provider=config.provider,
        collection=config.collection,
    )


def _search_earth_search(request: RasterScenePlanRequest) -> list[RasterScene]:
    """调用 Earth Search STAC API 搜索候选 scene。"""

    config = get_raster_data_source_config(request.data_source)
    payload = {
        "collections": [config.collection],
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


def _deduplicate_scenes_by_id(scenes: list[RasterScene]) -> list[RasterScene]:
    """按 scene_id 去重，保留第一次出现的 scene。"""

    seen_scene_ids = set()
    deduplicated_scenes = []

    for scene in scenes:
        if scene.scene_id in seen_scene_ids:
            continue

        seen_scene_ids.add(scene.scene_id)
        deduplicated_scenes.append(scene)

    return deduplicated_scenes


def _scene_group_id(scene: RasterScene) -> str:
    """从 Sentinel-2 scene_id 中提取空间分组 ID。"""

    parts = scene.scene_id.split("_")
    if len(parts) >= 2 and parts[1]:
        return parts[1]

    return scene.scene_id


def _sort_scenes_by_cloud_cover(scenes: list[RasterScene]) -> list[RasterScene]:
    """按云量从低到高排序，云量缺失的 scene 放到最后。"""

    return sorted(
        scenes,
        key=lambda scene: (
            scene.cloud_cover is None,
            scene.cloud_cover if scene.cloud_cover is not None else 101,
        ),
    )


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


def _extract_band_urls(
    scene: RasterScene,
    required_bands: list[str],
    band_assets: dict[str, str],
) -> dict[str, str]:
    """从 scene assets 中提取请求波段对应的下载 URL。"""

    band_urls = {}

    for band in required_bands:
        asset_key = band_assets[band]
        asset_url = scene.assets.get(asset_key)

        if not asset_url:
            raise RasterDownloadError(
                f"Scene {scene.scene_id} is missing asset for band {band}."
            )

        band_urls[band] = asset_url

    return band_urls
