from pathlib import Path

from pydantic import BaseModel, Field, field_validator

EARTH_SEARCH_COLLECTION = "sentinel-2-l2a"
EARTH_SEARCH_BAND_ASSETS = {
    "B04": "red",
    "B08": "nir",
}


class RasterDownloadError(RuntimeError):
    """栅格数据下载失败时抛出的错误。"""


class RasterClipError(RuntimeError):
    """栅格裁剪失败时抛出的错误。"""


class AOIRequest(BaseModel):
    """AOI 解析请求。

    上游 LLM 应把用户地点转换成包含上级行政区的消歧查询字符串，
    例如 ``Hangzhou, Zhejiang, China``。

    Attributes:
        query: 可直接交给 Nominatim 搜索的地点查询字符串。
        output_dir: AOI 边界文件输出目录。
        limit: 最多请求的候选结果数量。
    """

    query: str = Field(min_length=1)
    output_dir: Path
    limit: int = Field(default=5, ge=1, le=10)


class AOIResult(BaseModel):
    """AOI 解析结果。

    Attributes:
        name: 匹配到的地点名称。
        boundary_geojson_path: 提取出的目标 AOI GeoJSON 路径。
        bbox: 最小覆盖目标行政区的 bbox，顺序为
            ``[min_lon, min_lat, max_lon, max_lat]``。
        area_km2: 根据 bbox 估算的近似面积，单位为平方千米。
        spatial_scale: 空间尺度分类，例如 ``local``、``regional``。
        source: AOI 来源。
    """

    name: str
    boundary_geojson_path: str
    bbox: list[float]
    area_km2: float
    spatial_scale: str
    source: str


class RasterDownloadRequest(BaseModel):
    """栅格数据下载请求。

    Attributes:
        bbox: 查询范围，顺序为 ``[min_lon, min_lat, max_lon, max_lat]``。
        start_date: 查询开始日期，格式为 ``YYYY-MM-DD``。
        end_date: 查询结束日期，格式为 ``YYYY-MM-DD``。
        max_cloud_cover: 允许的最大云量百分比。
        required_bands: 需要下载的波段，例如 ``B04`` 和 ``B08``。
        output_dir: 本地输出目录。
        provider: 数据提供方标识。V1 默认使用 Earth Search。
        collection: STAC collection 名称。
        limit: 最多请求的候选 scene 数量。
    """

    bbox: list[float] = Field(min_length=4, max_length=4)
    start_date: str
    end_date: str
    max_cloud_cover: float = Field(ge=0, le=100)
    required_bands: list[str] = Field(min_length=1)
    output_dir: Path
    provider: str = "earth_search"
    collection: str = EARTH_SEARCH_COLLECTION
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("required_bands")
    @classmethod
    def normalize_required_bands(cls, bands: list[str]) -> list[str]:
        normalized_bands = [band.upper() for band in bands]
        unsupported_bands = [
            band for band in normalized_bands if band not in EARTH_SEARCH_BAND_ASSETS
        ]

        if unsupported_bands:
            unsupported_band_names = ", ".join(unsupported_bands)
            raise ValueError(f"Unsupported raster bands: {unsupported_band_names}")

        return normalized_bands


class RasterScene(BaseModel):
    """从 STAC 搜索结果中提取出的候选栅格 scene。"""

    scene_id: str
    datetime: str | None = None
    cloud_cover: float | None = None
    assets: dict[str, str] = Field(default_factory=dict)


class RasterDownloadResult(BaseModel):
    """栅格数据下载结果。"""

    selected_scene: str
    band_paths: dict[str, str]
    provider: str
    collection: str


class RasterClipRequest(BaseModel):
    """栅格裁剪请求。

    Attributes:
        raster_path: 输入 GeoTIFF 路径。当前假设它是单个波段文件。
        boundary_geojson_path: AOI GeoJSON 路径。
        output_path: 裁剪后 GeoTIFF 输出路径。
    """

    raster_path: Path
    boundary_geojson_path: Path
    output_path: Path


class RasterClipResult(BaseModel):
    """栅格裁剪结果。"""

    source_raster_path: str
    boundary_geojson_path: str
    clipped_raster_path: str
