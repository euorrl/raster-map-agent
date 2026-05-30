from pydantic import BaseModel

DEFAULT_RASTER_DATA_SOURCE = "sentinel2"
DEFAULT_INDEX_DATA_SOURCE = DEFAULT_RASTER_DATA_SOURCE


class RasterDataSourceConfig(BaseModel):
    """遥感数据源配置。

    Attributes:
        name: 数据源名称，例如 ``sentinel2``。
        provider: STAC provider 标识。
        collection: STAC collection 名称。
        band_assets: 项目内部 band 名称到 STAC asset key 的映射。
        enabled_for_raster_prepare: 当前数据准备工具是否已经接入该数据源。
    """

    name: str
    provider: str
    collection: str
    band_assets: dict[str, str]
    enabled_for_raster_prepare: bool = False


class IndexDataSourceConfig(BaseModel):
    """某个指数在某个数据源下的波段角色配置。"""

    data_source: str
    band_roles: dict[str, str]

    @property
    def required_bands(self) -> list[str]:
        """返回该数据源下计算指数所需的源波段。"""

        return list(self.band_roles.values())


class RasterRenderConfig(BaseModel):
    """某个指数产品的默认渲染配置。"""

    vmin: float
    vmax: float
    colormap: str


class IndexConfig(BaseModel):
    """栅格指数配置。"""

    name: str
    index_formula: str
    render_config: RasterRenderConfig
    data_sources: dict[str, IndexDataSourceConfig]

    @property
    def required_bands(self) -> list[str]:
        """返回默认数据源下的所需波段，兼容当前 mock workflow。"""

        return self.data_sources[DEFAULT_INDEX_DATA_SOURCE].required_bands


class RasterProductConfig(BaseModel):
    """指数和数据源解析后的完整产品配置。"""

    index_name: str
    data_source: str
    required_bands: list[str]
    band_roles: dict[str, str]
    index_formula: str
    render_config: RasterRenderConfig
    provider: str
    collection: str
    band_assets: dict[str, str]
    enabled_for_raster_prepare: bool


RASTER_DATA_SOURCE_REGISTRY: dict[str, RasterDataSourceConfig] = {
    "sentinel2": RasterDataSourceConfig(
        name="sentinel2",
        provider="earth_search",
        collection="sentinel-2-l2a",
        band_assets={
            "B02": "blue",
            "B03": "green",
            "B04": "red",
            "B05": "rededge1",
            "B08": "nir",
            "B11": "swir16",
            "B12": "swir22",
        },
        enabled_for_raster_prepare=True,
    ),
    "landsat": RasterDataSourceConfig(
        name="landsat",
        provider="earth_search",
        collection="landsat-c2-l2",
        band_assets={
            "B02": "blue",
            "B03": "green",
            "B04": "red",
            "B05": "nir08",
            "B06": "swir16",
            "B07": "swir22",
        },
        enabled_for_raster_prepare=False,
    ),
}

INDEX_REGISTRY: dict[str, IndexConfig] = {
    # 植被绿度与覆盖度，最通用的植被指数。
    "NDVI": IndexConfig(
        name="NDVI",
        index_formula="(nir - red) / (nir + red)",
        render_config=RasterRenderConfig(
            vmin=-0.2,
            vmax=0.8,
            colormap="greens",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"red": "B04", "nir": "B08"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"red": "B04", "nir": "B05"},
            ),
        },
    ),
    # 土壤调节植被指数，适合稀疏植被、裸土背景明显的区域。
    "SAVI": IndexConfig(
        name="SAVI",
        index_formula="1.5 * (nir - red) / (nir + red + 0.5)",
        render_config=RasterRenderConfig(
            vmin=-0.2,
            vmax=0.8,
            colormap="YlGn",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"red": "B04", "nir": "B08"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"red": "B04", "nir": "B05"},
            ),
        },
    ),
    # 水体指数，使用 Green/NIR 版本，适合增强水体。
    "NDWI": IndexConfig(
        name="NDWI",
        index_formula="(green - nir) / (green + nir)",
        render_config=RasterRenderConfig(
            vmin=-0.5,
            vmax=0.5,
            colormap="Blues",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"green": "B03", "nir": "B08"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"green": "B03", "nir": "B05"},
            ),
        },
    ),
    # 水分指数，适合植被含水量、地表湿度、干旱胁迫分析。
    "NDMI": IndexConfig(
        name="NDMI",
        index_formula="(nir - swir) / (nir + swir)",
        render_config=RasterRenderConfig(
            vmin=-0.5,
            vmax=0.5,
            colormap="BrBG",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"nir": "B08", "swir": "B11"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"nir": "B05", "swir": "B06"},
            ),
        },
    ),
    # 建成区指数，适合突出城市建成区、不透水面和裸地。
    "NDBI": IndexConfig(
        name="NDBI",
        index_formula="(swir - nir) / (swir + nir)",
        render_config=RasterRenderConfig(
            vmin=-0.5,
            vmax=0.5,
            colormap="Oranges",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"swir": "B11", "nir": "B08"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"swir": "B06", "nir": "B05"},
            ),
        },
    ),
    # 燃烧指数，适合火烧迹地、火灾影响和植被受损分析。
    "NBR": IndexConfig(
        name="NBR",
        index_formula="(nir - swir2) / (nir + swir2)",
        render_config=RasterRenderConfig(
            vmin=-0.5,
            vmax=0.8,
            colormap="RdYlGn",
        ),
        data_sources={
            "sentinel2": IndexDataSourceConfig(
                data_source="sentinel2",
                band_roles={"nir": "B08", "swir2": "B12"},
            ),
            "landsat": IndexDataSourceConfig(
                data_source="landsat",
                band_roles={"nir": "B05", "swir2": "B07"},
            ),
        },
    ),
}


def get_index_config(index_name: str) -> IndexConfig:
    """返回已支持栅格指数的配置，匹配时不区分大小写。"""

    normalized_index_name = index_name.upper()

    try:
        return INDEX_REGISTRY[normalized_index_name]
    except KeyError as error:
        raise ValueError(f"Unsupported index: {index_name}") from error


def get_raster_data_source_config(data_source: str) -> RasterDataSourceConfig:
    """返回已注册数据源配置，匹配时不区分大小写。"""

    normalized_data_source = data_source.lower()

    try:
        return RASTER_DATA_SOURCE_REGISTRY[normalized_data_source]
    except KeyError as error:
        raise ValueError(f"Unsupported raster data source: {data_source}") from error


def get_raster_prepare_data_source_config(data_source: str) -> RasterDataSourceConfig:
    """返回当前 raster_prepare 已接入的数据源配置。"""

    config = get_raster_data_source_config(data_source)
    if config.enabled_for_raster_prepare:
        return config

    supported_sources = [
        name
        for name, source_config in RASTER_DATA_SOURCE_REGISTRY.items()
        if source_config.enabled_for_raster_prepare
    ]
    raise ValueError(
        f"Unsupported raster data source: {data_source}. "
        f"V1 raster prepare supports: {', '.join(supported_sources)}"
    )


def resolve_raster_product_config(
    index_name: str,
    data_source: str = DEFAULT_INDEX_DATA_SOURCE,
) -> RasterProductConfig:
    """解析指数和数据源，返回完整产品配置。"""

    index_config = get_index_config(index_name)
    source_config = get_raster_data_source_config(data_source)

    try:
        index_source_config = index_config.data_sources[source_config.name]
    except KeyError as error:
        raise ValueError(
            f"Index {index_config.name} does not support data source: "
            f"{source_config.name}"
        ) from error

    return RasterProductConfig(
        index_name=index_config.name,
        data_source=source_config.name,
        required_bands=index_source_config.required_bands,
        band_roles=index_source_config.band_roles,
        index_formula=index_config.index_formula,
        render_config=index_config.render_config,
        provider=source_config.provider,
        collection=source_config.collection,
        band_assets=source_config.band_assets,
        enabled_for_raster_prepare=source_config.enabled_for_raster_prepare,
    )
