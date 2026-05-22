"""行政区 AOI 边界下载与尺度判断工具。"""

import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from app.tools.raster.schemas import AOIRequest, AOIResult, RasterDownloadError
from app.utils.logging import get_logger

logger = get_logger(__name__)

GEBOUNDARIES_API_TEMPLATE = (
    "https://www.geoboundaries.org/api/current/{release_type}/{iso3}/{admin_level}/"
)
LOCAL_SCALE_MAX_AREA_KM2 = 5_000
REGIONAL_SCALE_MAX_AREA_KM2 = 200_000
KM_PER_DEGREE_LAT = 111.32
BOUNDARY_NAME_KEYS = (
    "shapeName",
    "shapeISO",
    "shapeID",
    "name",
    "NAME",
    "NAME_0",
    "NAME_1",
    "NAME_2",
    "ADM0_NAME",
    "ADM1_NAME",
    "ADM2_NAME",
)


def resolve_administrative_aoi(request: AOIRequest) -> AOIResult:
    """下载行政区边界，并返回后续栅格下载需要的 AOI 信息。

    Args:
        request: 由上游 LLM 生成的行政区请求，例如国家代码、行政区级别和名称。

    Returns:
        包含 shapefile zip、目标行政区 GeoJSON、bbox、面积和尺度分类的结果。
    """

    output_dir = request.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Resolving administrative AOI name=%s iso3=%s admin_level=%s",
        request.name,
        request.iso3,
        request.admin_level,
    )
    metadata = _fetch_geoboundaries_metadata(request)
    geojson_url = _require_metadata_url(metadata, "gjDownloadURL")

    geojson = _get_json(geojson_url)
    feature = _select_boundary_feature(geojson, request.name)
    selected_geojson = {"type": "FeatureCollection", "features": [feature]}
    boundary_geojson_path = output_dir / _build_boundary_geojson_name(request)
    boundary_geojson_path.write_text(
        json.dumps(selected_geojson, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved AOI GeoJSON path=%s", boundary_geojson_path)

    bbox = _geometry_bbox(feature["geometry"])
    area_km2 = _estimate_bbox_area_km2(bbox)
    spatial_scale = _classify_spatial_scale(area_km2)
    logger.info(
        "Resolved AOI name=%s bbox=%s area_km2=%.2f spatial_scale=%s",
        _feature_name(feature) or request.name,
        bbox,
        area_km2,
        spatial_scale,
    )

    return AOIResult(
        name=_feature_name(feature) or request.name,
        iso3=request.iso3,
        admin_level=request.admin_level,
        boundary_geojson_path=str(boundary_geojson_path),
        bbox=bbox,
        area_km2=area_km2,
        spatial_scale=spatial_scale,
        source="geoBoundaries",
    )


def _fetch_geoboundaries_metadata(request: AOIRequest) -> dict:
    """请求 geoBoundaries 元数据，获取边界文件下载地址。"""

    url = GEBOUNDARIES_API_TEMPLATE.format(
        release_type=request.release_type,
        iso3=request.iso3,
        admin_level=request.admin_level,
    )
    logger.info("Querying geoBoundaries metadata url=%s", url)
    return _get_json(url)


def _require_metadata_url(metadata: dict, key: str) -> str:
    """从 geoBoundaries 元数据中读取必须存在的下载链接。"""

    value = metadata.get(key)
    if not value:
        raise RasterDownloadError(f"geoBoundaries metadata missing URL: {key}")

    return value


def _get_json(url: str) -> dict:
    """请求 JSON 接口并解析为字典。"""

    try:
        with urlopen(url, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        raise RasterDownloadError(f"Failed to query AOI boundary API: {url}") from error


def _select_boundary_feature(geojson: dict, boundary_name: str) -> dict:
    """从行政区 FeatureCollection 中选出目标行政区。"""

    features = geojson.get("features", [])
    logger.info("Searching AOI boundary candidates count=%s", len(features))
    normalized_target = _normalize_name(boundary_name)

    for feature in features:
        if _normalize_name(_feature_name(feature)) == normalized_target:
            logger.info("Matched AOI boundary name=%s", _feature_name(feature))
            return feature

    for feature in features:
        feature_name = _normalize_name(_feature_name(feature))
        if normalized_target in feature_name or feature_name in normalized_target:
            logger.info("Matched AOI boundary name=%s", _feature_name(feature))
            return feature

    sample_names = [
        _feature_name(feature) for feature in features[:10] if _feature_name(feature)
    ]
    raise RasterDownloadError(
        f"AOI boundary not found: {boundary_name}. "
        f"candidates={len(features)} sample_names={sample_names}"
    )


def _feature_name(feature: dict) -> str:
    """按常见字段顺序读取行政区名称。"""

    properties = feature.get("properties", {})
    for key in BOUNDARY_NAME_KEYS:
        value = properties.get(key)
        if value:
            return str(value)

    return ""


def _normalize_name(name: str) -> str:
    """把名称转换成适合粗匹配的形式。"""

    return re.sub(r"\s+", " ", name).strip().casefold()


def _geometry_bbox(geometry: dict) -> list[float]:
    """从 GeoJSON geometry 中计算最小 bbox。"""

    coordinates = list(_iter_coordinates(geometry.get("coordinates", [])))
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


def _build_boundary_geojson_name(request: AOIRequest) -> str:
    """生成目标行政区 GeoJSON 的本地文件名。"""

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", request.name).strip("_")
    return f"{safe_name}_{request.iso3}_{request.admin_level}.geojson"
