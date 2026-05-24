from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

EARTH_SEARCH_COLLECTION = "sentinel-2-l2a"
EARTH_SEARCH_BAND_ASSETS = {
    "B04": "red",
    "B08": "nir",
}
DEFAULT_RASTER_DATA_SOURCE = "sentinel2"

AOI_DIRNAME = "aoi"
RASTER_DIRNAME = "raster"
CLIPPED_RASTER_DIRNAME = "clipped_raster"


class RasterDownloadError(RuntimeError):
    """栅格数据下载失败时抛出的错误。"""


class RasterClipError(RuntimeError):
    """栅格裁剪失败时抛出的错误。"""


class RasterDataSourceConfig(BaseModel):
    """栅格数据源的内部配置。

    V1 只登记 Sentinel-2。保留 data_source 字段是为了让上游 plan
    有稳定的参数协议，但当前不承诺多卫星/多 provider 支持。
    """

    data_source: str
    provider: str
    collection: str
    band_assets: dict[str, str]


RASTER_DATA_SOURCE_CONFIGS: dict[str, RasterDataSourceConfig] = {
    DEFAULT_RASTER_DATA_SOURCE: RasterDataSourceConfig(
        data_source=DEFAULT_RASTER_DATA_SOURCE,
        provider="earth_search",
        collection=EARTH_SEARCH_COLLECTION,
        band_assets=EARTH_SEARCH_BAND_ASSETS,
    )
}
SUPPORTED_RASTER_DATA_SOURCES = tuple(RASTER_DATA_SOURCE_CONFIGS)


def get_raster_data_source_config(data_source: str) -> RasterDataSourceConfig:
    """根据数据源名称返回内部 STAC 配置。"""

    try:
        return RASTER_DATA_SOURCE_CONFIGS[data_source]
    except KeyError as error:
        supported_sources = ", ".join(SUPPORTED_RASTER_DATA_SOURCES)
        raise ValueError(
            f"Unsupported raster data source: {data_source}. "
            f"V1 only supports: {supported_sources}"
        ) from error


class AOIRequest(BaseModel):
    """AOI 解析请求。

    上游 LLM 应把用户地点转换成包含上级行政区的查询字符串，
    例如 ``Hangzhou, Zhejiang, China``。

    Attributes:
        query: 可直接交给 Nominatim 搜索的地点查询字符串。
        workspace_dir: 当前任务的工作目录。
        limit: 最多请求的候选结果数量。
    """

    query: str = Field(min_length=1)
    workspace_dir: Path
    limit: int = Field(default=5, ge=1, le=10)

    @property
    def output_dir(self) -> Path:
        """AOI GeoJSON 自动保存目录。"""

        return self.workspace_dir / AOI_DIRNAME


class AOIResult(BaseModel):
    """AOI 解析结果。

    Attributes:
        name: 匹配到的地点名称。
        boundary_geojson_path: 提取出的目标 AOI GeoJSON 路径。
        bbox: 最小覆盖目标行政区的 bbox，顺序为
            ``[min_lon, min_lat, max_lon, max_lat]``。
        area_km2: 根据 bbox 估算的近似面积，单位为平方千米。
        source: AOI 来源。
    """

    name: str
    boundary_geojson_path: str
    bbox: list[float]
    area_km2: float
    source: str


class RasterScenePlanRequest(BaseModel):
    """栅格 scene 规划请求。

    Attributes:
        bbox: STAC 查询范围，顺序为 ``[min_lon, min_lat, max_lon, max_lat]``。
        boundary_geojson_path: AOI GeoJSON 路径，用于 coverage 检测。
        start_date: 查询开始日期，格式为 ``YYYY-MM-DD``。
        end_date: 查询结束日期，格式为 ``YYYY-MM-DD``。
        max_cloud_cover: 允许的最大云量百分比。
        required_bands: 需要下载的波段，例如 ``B04`` 和 ``B08``。
        data_source: 上游 plan 选择的数据源。V1 先只实现 ``sentinel2``。
        limit: 最多请求的候选 scene 数量。V1 默认请求 100 条。
        max_selected_scenes: 最终进入下载 plan 的最大 scene 数量。
        contribution_tolerance: 新增覆盖贡献接近最优值时，允许用云量决定优先级。
        min_scene_overlap_ratio: 候选 scene 至少需要覆盖 AOI 的比例。
        min_coverage_ratio: scene plan 对 AOI 的最低可接受覆盖率。
    """

    bbox: list[float] = Field(min_length=4, max_length=4)
    boundary_geojson_path: Path | None = None
    start_date: str
    end_date: str
    max_cloud_cover: float = Field(ge=0, le=100)
    required_bands: list[str] = Field(min_length=1)
    data_source: str = DEFAULT_RASTER_DATA_SOURCE
    limit: int = Field(default=100, ge=1, le=100)
    max_selected_scenes: int = Field(default=20, ge=1, le=100)
    contribution_tolerance: float = Field(default=0.95, ge=0, le=1)
    min_scene_overlap_ratio: float = Field(default=0, ge=0, le=1)
    min_coverage_ratio: float = Field(default=0.7, ge=0, le=1)

    @model_validator(mode="after")
    def validate_scene_plan_request(self):
        config = get_raster_data_source_config(self.data_source)
        unsupported_bands = [
            band for band in self.required_bands if band not in config.band_assets
        ]
        if unsupported_bands:
            unsupported_band_names = ", ".join(unsupported_bands)
            raise ValueError(f"Unsupported raster bands: {unsupported_band_names}")

        return self

    @field_validator("required_bands")
    @classmethod
    def normalize_required_bands(cls, bands: list[str]) -> list[str]:
        """把波段名称统一转为大写，方便后续查配置。"""

        return [band.upper() for band in bands]

    @field_validator("data_source")
    @classmethod
    def normalize_data_source(cls, data_source: str) -> str:
        """把数据源名称统一转为小写，当前只允许 sentinel2。"""

        return data_source.lower()


class RasterScene(BaseModel):
    """从 STAC 搜索结果中提取出的候选栅格 scene。"""

    scene_id: str
    datetime: str | None = None
    cloud_cover: float | None = None
    bbox: list[float] | None = None
    geometry: dict | None = None
    assets: dict[str, str] = Field(default_factory=dict)


class RasterSceneCandidateStore(BaseModel):
    """可跨多次 scene plan 调用累积的候选 scene 池。"""

    scenes: dict[str, RasterScene] = Field(default_factory=dict)


class RasterDownloadAsset(BaseModel):
    """下载计划中的单个 scene band asset。"""

    scene_id: str
    band: str
    url: str


class RasterScenePlanDiagnostics(BaseModel):
    """scene plan 诊断信息，用于后续 ReAct observation。"""

    coverage_status: str
    coverage_ratio: float
    min_coverage_ratio: float = Field(default=1, ge=0, le=1)
    is_retriable: bool = False
    failure_reason: str | None = None
    message: str
    suggested_actions: list[str] = Field(default_factory=list)
    selected_scene_count: int = 0
    missing_geometry_scene_ids: list[str] = Field(default_factory=list)


class RasterScenePlanResult(BaseModel):
    """栅格 scene 规划结果。"""

    scene_ids: list[str]
    assets: list[RasterDownloadAsset]
    diagnostics: RasterScenePlanDiagnostics
    data_source: str
    provider: str
    collection: str


class RasterDownloadRequest(BaseModel):
    """栅格下载请求。"""

    plan: RasterScenePlanResult
    workspace_dir: Path

    @property
    def output_dir(self) -> Path:
        """原始 raster 自动保存目录。"""

        return self.workspace_dir / RASTER_DIRNAME


class RasterDownloadResult(BaseModel):
    """栅格下载结果。"""

    scene_ids: list[str]
    band_paths: dict[str, list[str]]
    data_source: str
    provider: str
    collection: str


class RasterClipRequest(BaseModel):
    """栅格裁剪请求。

    Attributes:
        raster_path: 输入 GeoTIFF 路径。当前假设它是单个波段文件。
        boundary_geojson_path: AOI GeoJSON 路径。
        workspace_dir: 当前任务的工作目录。
        output_filename: 可选输出文件名，不传则自动生成。
    """

    raster_path: Path
    boundary_geojson_path: Path
    workspace_dir: Path
    output_filename: str | None = None

    @property
    def output_path(self) -> Path:
        """裁剪后 raster 自动保存路径。"""

        filename = self.output_filename or f"{self.raster_path.stem}_clipped.tif"
        return self.workspace_dir / CLIPPED_RASTER_DIRNAME / filename


class RasterClipResult(BaseModel):
    """栅格裁剪结果。"""

    source_raster_path: str
    boundary_geojson_path: str
    clipped_raster_path: str
