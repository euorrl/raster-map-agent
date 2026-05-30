"""栅格 scene 下载计划构建。"""

import json
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shapely.geometry import shape
from shapely.ops import unary_union

from app.registry import (
    DEFAULT_RASTER_DATA_SOURCE,
    get_raster_prepare_data_source_config,
)
from app.tools.raster_prepare.schemas import (
    RasterDownloadAsset,
    RasterDownloadError,
    RasterScene,
    RasterSceneCandidateStore,
    RasterScenePlanDiagnostics,
    RasterScenePlanResult,
    RasterScenePlanRequest,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

EARTH_SEARCH_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COVERAGE_COMPLETE_THRESHOLD = 0.999


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
        max_selected_scenes=request.max_selected_scenes,
        contribution_tolerance=request.contribution_tolerance,
        min_scene_overlap_ratio=request.min_scene_overlap_ratio,
        min_coverage_ratio=request.min_coverage_ratio,
        data_source=request.data_source,
        boundary_geojson_path=request.boundary_geojson_path,
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
        store.scenes.setdefault(scene.scene_id, scene)


def build_raster_scene_plan_from_candidates(
    store: RasterSceneCandidateStore,
    required_bands: list[str],
    max_selected_scenes: int,
    contribution_tolerance: float,
    min_scene_overlap_ratio: float,
    min_coverage_ratio: float,
    data_source: str = DEFAULT_RASTER_DATA_SOURCE,
    boundary_geojson_path: str | None = None,
) -> RasterScenePlanResult:
    """从全局候选池中选择覆盖贡献最大的 scenes，并生成下载计划。"""

    config = get_raster_prepare_data_source_config(data_source)
    candidate_scenes = list(store.scenes.values())

    if not candidate_scenes:
        return RasterScenePlanResult(
            scene_ids=[],
            assets=[],
            diagnostics=_build_no_scene_diagnostics(min_coverage_ratio),
            data_source=config.name,
            provider=config.provider,
            collection=config.collection,
        )

    selected_scenes = _select_scenes_by_coverage(
        candidate_scenes=candidate_scenes,
        boundary_geojson_path=boundary_geojson_path,
        max_selected_scenes=max_selected_scenes,
        contribution_tolerance=contribution_tolerance,
        min_scene_overlap_ratio=min_scene_overlap_ratio,
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
        diagnostics=_build_coverage_diagnostics(
            selected_scenes,
            boundary_geojson_path,
            min_coverage_ratio,
        ),
        data_source=config.name,
        provider=config.provider,
        collection=config.collection,
    )


def _build_no_scene_diagnostics(
    min_coverage_ratio: float,
) -> RasterScenePlanDiagnostics:
    """构造没有找到候选 scene 时的可重试诊断。"""

    return RasterScenePlanDiagnostics(
        coverage_status="not_covered",
        coverage_ratio=0,
        min_coverage_ratio=min_coverage_ratio,
        is_retriable=True,
        failure_reason="no_raster_scenes_found",
        message=(
            "No raster scenes found for the requested parameters. "
            "Try expanding date range or relaxing cloud cover."
        ),
        suggested_actions=[
            "expand_date_range",
            "increase_max_cloud_cover",
        ],
        selected_scene_count=0,
    )


def _search_earth_search(request: RasterScenePlanRequest) -> list[RasterScene]:
    """调用 Earth Search STAC API 搜索候选 scene。"""

    config = get_raster_prepare_data_source_config(request.data_source)
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
        bbox=item.get("bbox"),
        geometry=item.get("geometry"),
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


def _select_scenes_by_coverage(
    candidate_scenes: list[RasterScene],
    boundary_geojson_path: str | None,
    max_selected_scenes: int,
    contribution_tolerance: float,
    min_scene_overlap_ratio: float,
) -> list[RasterScene]:
    """优先选择对 AOI 未覆盖区域贡献最大的 scenes。"""

    fallback_scenes = _sort_scenes_by_cloud_cover(candidate_scenes)[
        :max_selected_scenes
    ]

    if boundary_geojson_path is None:
        return fallback_scenes

    try:
        aoi_geometry = _load_aoi_geometry(boundary_geojson_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return fallback_scenes

    if aoi_geometry.area == 0:
        return fallback_scenes

    selected_scenes = []
    remaining_scenes = list(candidate_scenes)
    uncovered_geometry = aoi_geometry

    while remaining_scenes and len(selected_scenes) < max_selected_scenes:
        scored_scenes = []
        for scene in remaining_scenes:
            geometry = _scene_geometry(scene)
            if geometry is None:
                continue

            overlap_area = geometry.intersection(aoi_geometry).area
            overlap_ratio = overlap_area / aoi_geometry.area
            if overlap_ratio < min_scene_overlap_ratio:
                continue

            contribution_area = geometry.intersection(uncovered_geometry).area
            if contribution_area <= 0:
                continue

            scored_scenes.append((scene, geometry, contribution_area))

        if not scored_scenes:
            break

        max_contribution = max(score[2] for score in scored_scenes)
        competitive_scenes = [
            score
            for score in scored_scenes
            if score[2] >= max_contribution * contribution_tolerance
        ]
        selected_scene, selected_geometry, _contribution = min(
            competitive_scenes,
            key=lambda score: (
                score[0].cloud_cover is None,
                score[0].cloud_cover if score[0].cloud_cover is not None else 101,
                -score[2],
                score[0].scene_id,
            ),
        )

        selected_scenes.append(selected_scene)
        remaining_scenes = [
            scene
            for scene in remaining_scenes
            if scene.scene_id != selected_scene.scene_id
        ]
        uncovered_geometry = uncovered_geometry.difference(selected_geometry)

        selected_geometries = [
            geometry
            for geometry in (_scene_geometry(scene) for scene in selected_scenes)
            if geometry is not None
        ]
        if selected_geometries:
            coverage_ratio = _coverage_ratio(
                aoi_geometry,
                unary_union(selected_geometries),
            )
            if coverage_ratio >= COVERAGE_COMPLETE_THRESHOLD:
                break

    if selected_scenes:
        return selected_scenes

    return fallback_scenes


def _scene_geometry(scene: RasterScene):
    """读取 scene footprint geometry，无法解析时返回 None。"""

    if not scene.geometry:
        return None

    try:
        geometry = shape(scene.geometry)
    except (TypeError, ValueError):
        return None

    if geometry.is_empty:
        return None

    return geometry


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


def _build_coverage_diagnostics(
    selected_scenes: list[RasterScene],
    boundary_geojson_path: str | None,
    min_coverage_ratio: float,
) -> RasterScenePlanDiagnostics:
    """用 Shapely 检查选中 scene footprints 是否覆盖真实 AOI。"""

    if boundary_geojson_path is None:
        return RasterScenePlanDiagnostics(
            coverage_status="unknown",
            coverage_ratio=0,
            min_coverage_ratio=min_coverage_ratio,
            is_retriable=False,
            failure_reason="missing_aoi_geometry",
            message="AOI GeoJSON path is missing, so scene coverage cannot be checked.",
            suggested_actions=[],
            selected_scene_count=len(selected_scenes),
        )

    try:
        aoi_geometry = _load_aoi_geometry(boundary_geojson_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return RasterScenePlanDiagnostics(
            coverage_status="unknown",
            coverage_ratio=0,
            min_coverage_ratio=min_coverage_ratio,
            is_retriable=False,
            failure_reason="invalid_aoi_geometry",
            message=f"AOI GeoJSON cannot be used for coverage check: {error}",
            suggested_actions=[],
            selected_scene_count=len(selected_scenes),
        )

    scene_geometries = []
    missing_geometry_scene_ids = []

    for scene in selected_scenes:
        if not scene.geometry:
            missing_geometry_scene_ids.append(scene.scene_id)
            continue

        try:
            geometry = shape(scene.geometry)
        except (TypeError, ValueError):
            missing_geometry_scene_ids.append(scene.scene_id)
            continue

        if geometry.is_empty:
            missing_geometry_scene_ids.append(scene.scene_id)
            continue

        scene_geometries.append(geometry)

    if not scene_geometries:
        return RasterScenePlanDiagnostics(
            coverage_status="unknown",
            coverage_ratio=0,
            min_coverage_ratio=min_coverage_ratio,
            is_retriable=False,
            failure_reason="missing_scene_geometry",
            message="Selected scenes do not include usable footprint geometry.",
            suggested_actions=[],
            selected_scene_count=len(selected_scenes),
            missing_geometry_scene_ids=missing_geometry_scene_ids,
        )

    union_geometry = unary_union(scene_geometries)
    coverage_ratio = _coverage_ratio(aoi_geometry, union_geometry)

    if missing_geometry_scene_ids:
        return RasterScenePlanDiagnostics(
            coverage_status="unknown",
            coverage_ratio=coverage_ratio,
            min_coverage_ratio=min_coverage_ratio,
            is_retriable=False,
            failure_reason="missing_scene_geometry",
            message=(
                "Some selected scenes are missing usable footprint geometry, "
                "so coverage cannot be trusted."
            ),
            suggested_actions=[],
            selected_scene_count=len(selected_scenes),
            missing_geometry_scene_ids=missing_geometry_scene_ids,
        )

    if coverage_ratio >= min_coverage_ratio:
        return RasterScenePlanDiagnostics(
            coverage_status="covered",
            coverage_ratio=coverage_ratio,
            min_coverage_ratio=min_coverage_ratio,
            is_retriable=False,
            message=(
                f"Selected scenes cover {coverage_ratio:.2%} of the AOI geometry, "
                f"meeting the minimum required coverage {min_coverage_ratio:.2%}."
            ),
            selected_scene_count=len(selected_scenes),
        )

    return RasterScenePlanDiagnostics(
        coverage_status="not_covered",
        coverage_ratio=coverage_ratio,
        min_coverage_ratio=min_coverage_ratio,
        is_retriable=True,
        failure_reason="insufficient_spatial_coverage",
        message=(
            f"Selected scenes cover {coverage_ratio:.2%} of the AOI geometry, "
            f"below the minimum required coverage {min_coverage_ratio:.2%}. "
            "Try expanding date range or relaxing cloud cover."
        ),
        suggested_actions=[
            "expand_date_range",
            "increase_max_cloud_cover",
        ],
        selected_scene_count=len(selected_scenes),
    )


def _load_aoi_geometry(boundary_geojson_path: str):
    """从 AOI GeoJSON 文件读取真实 AOI geometry。"""

    with open(boundary_geojson_path, encoding="utf-8") as file:
        geojson = json.load(file)

    geojson_type = geojson.get("type")

    if geojson_type == "FeatureCollection":
        geometries = [
            shape(feature["geometry"])
            for feature in geojson.get("features", [])
            if feature.get("geometry")
        ]
        if not geometries:
            raise ValueError("FeatureCollection does not contain geometry.")

        geometry = unary_union(geometries)
    elif geojson_type == "Feature":
        geometry = shape(geojson["geometry"])
    else:
        geometry = shape(geojson)

    if geometry.is_empty:
        raise ValueError("AOI geometry is empty.")

    return geometry


def _coverage_ratio(aoi_geometry, union_geometry) -> float:
    """计算 scene union 对真实 AOI geometry 的覆盖比例。"""

    if aoi_geometry.area == 0:
        return 0

    covered_area = union_geometry.intersection(aoi_geometry).area
    return min(covered_area / aoi_geometry.area, 1)
