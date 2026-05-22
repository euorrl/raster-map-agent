from pathlib import Path

from pydantic import BaseModel, Field, field_validator


EARTH_SEARCH_COLLECTION = "sentinel-2-l2a"
EARTH_SEARCH_BAND_ASSETS = {
    "B04": "red",
    "B08": "nir",
}


class RasterDownloadError(RuntimeError):
    """栅格数据下载失败时抛出的错误。"""


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
