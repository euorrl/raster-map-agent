"""基于 Nominatim 的 AOI 边界解析工具。"""

import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.tools.raster.schemas import AOIRequest, AOIResult, RasterDownloadError
from app.utils.logging import get_logger

logger = get_logger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "raster-map-agent/0.1 portfolio demo"
LOCAL_SCALE_MAX_AREA_KM2 = 5_000
REGIONAL_SCALE_MAX_AREA_KM2 = 200_000
KM_PER_DEGREE_LAT = 111.32


def resolve_administrative_aoi(request: AOIRequest) -> AOIResult:
    """用 Nominatim 查询 AOI 边界，并返回栅格下载/裁剪需要的信息。

    Args:
        request: 包含消歧地点查询字符串和输出目录的 AOI 请求。

    Returns:
        包含目标 AOI GeoJSON、bbox、面积和尺度分类的结果。
    """

    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Resolving AOI query=%s", request.query)
    geojson = _search_nominatim(request)
    feature = _select_boundary_feature(geojson, request.query)
    selected_geojson = {"type": "FeatureCollection", "features": [feature]}

    name = _feature_name(feature) or request.query
    boundary_geojson_path = output_dir / _build_boundary_geojson_name(request.query)
    boundary_geojson_path.write_text(
        json.dumps(selected_geojson, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved AOI GeoJSON path=%s", boundary_geojson_path)

    bbox = _geometry_bbox(feature)
    area_km2 = _estimate_bbox_area_km2(bbox)
    spatial_scale = _classify_spatial_scale(area_km2)
    logger.info(
        "Resolved AOI name=%s bbox=%s area_km2=%.2f spatial_scale=%s",
        name,
        bbox,
        area_km2,
        spatial_scale,
    )

    return AOIResult(
        name=name,
        boundary_geojson_path=str(boundary_geojson_path),
        bbox=bbox,
        area_km2=area_km2,
        spatial_scale=spatial_scale,
        source="nominatim",
    )


def _search_nominatim(request: AOIRequest) -> dict:
    """请求 Nominatim，返回 GeoJSON 格式候选结果。"""

    params = {
        "q": request.query,
        "format": "geojson",
        "polygon_geojson": 1,
        "addressdetails": 1,
        "limit": request.limit,
    }
    url = f"{NOMINATIM_SEARCH_URL}?{urlencode(params)}"
    logger.info("Querying Nominatim url=%s", url)
    return _get_json(url)


def _get_json(url: str) -> dict:
    """请求 JSON 接口并解析为字典。"""

    request = Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT})

    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        raise RasterDownloadError(f"Failed to query AOI boundary API: {url}") from error


def _select_boundary_feature(geojson: dict, query: str) -> dict:
    """从 Nominatim 候选结果中选出第一个 polygon 边界。"""

    features = geojson.get("features", [])
    logger.info("Searching AOI boundary candidates count=%s", len(features))

    for feature in features:
        geometry_type = feature.get("geometry", {}).get("type")
        if geometry_type in {"Polygon", "MultiPolygon"}:
            logger.info(
                "Matched AOI boundary name=%s geometry_type=%s",
                _feature_name(feature),
                geometry_type,
            )
            return feature

    sample_names = [_feature_name(feature) for feature in features[:10]]
    raise RasterDownloadError(
        f"AOI boundary not found: {query}. "
        f"candidates={len(features)} sample_names={sample_names}"
    )


def _feature_name(feature: dict) -> str:
    """读取 Nominatim 返回的地点显示名称。"""

    properties = feature.get("properties", {})
    display_name = properties.get("display_name")
    if display_name:
        return str(display_name)

    name = properties.get("name")
    if name:
        return str(name)

    return ""


def _geometry_bbox(feature: dict) -> list[float]:
    """从 Nominatim feature 中计算最小 bbox。"""

    bbox = feature.get("bbox")
    if bbox and len(bbox) == 4:
        return [bbox[0], bbox[1], bbox[2], bbox[3]]

    coordinates = list(
        _iter_coordinates(feature.get("geometry", {}).get("coordinates", []))
    )
    if not coordinates:
        raise RasterDownloadError("AOI geometry has no coordinates")

    lons = [lon for lon, _lat in coordinates]
    lats = [lat for _lon, lat in coordinates]
    return [min(lons), min(lats), max(lons), max(lats)]


def _iter_coordinates(value):
    """递归遍历 GeoJSON 坐标数组。"""

    if not value:
        return

    if isinstance(value[0], (int, float)):
        yield value
        return

    for item in value:
        yield from _iter_coordinates(item)


def _estimate_bbox_area_km2(bbox: list[float]) -> float:
    """使用经纬度 bbox 估算面积，作为尺度判断的粗略依据。"""

    min_lon, min_lat, max_lon, max_lat = bbox
    center_lat = (min_lat + max_lat) / 2
    width_km = (
        (max_lon - min_lon) * KM_PER_DEGREE_LAT * math.cos(math.radians(center_lat))
    )
    height_km = (max_lat - min_lat) * KM_PER_DEGREE_LAT

    return abs(width_km * height_km)


def _classify_spatial_scale(area_km2: float) -> str:
    """根据面积粗分 AOI 空间尺度。"""

    if area_km2 <= LOCAL_SCALE_MAX_AREA_KM2:
        return "local"

    if area_km2 <= REGIONAL_SCALE_MAX_AREA_KM2:
        return "regional"

    return "continental"


def _build_boundary_geojson_name(name: str) -> str:
    """生成目标 AOI GeoJSON 的本地文件名。"""

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return f"{safe_name or 'aoi'}.geojson"
