import pytest

from app.registry import (
    INDEX_REGISTRY,
    get_index_config,
    get_raster_data_source_config,
    get_raster_prepare_data_source_config,
    resolve_raster_product_config,
)


def test_get_index_config_returns_ndvi_default_config():
    # 验证旧接口仍能返回默认 Sentinel-2 的 NDVI 波段和公式。
    config = get_index_config("ndvi")

    assert config.name == "NDVI"
    assert config.required_bands == ["B04", "B08"]
    assert config.index_formula == "(nir - red) / (nir + red)"
    assert config.render_config.vmin == -0.2
    assert config.render_config.vmax == 0.8
    assert config.render_config.colormap == "greens"


def test_get_index_config_returns_ndwi_config():
    config = get_index_config("ndwi")

    assert config.name == "NDWI"
    assert config.required_bands == ["B03", "B08"]
    assert config.index_formula == "(green - nir) / (green + nir)"
    assert config.render_config.vmin == -0.5
    assert config.render_config.vmax == 0.5
    assert config.render_config.colormap == "Blues"


@pytest.mark.parametrize(
    ("index_name", "required_bands", "formula", "colormap"),
    [
        ("SAVI", ["B04", "B08"], "1.5 * (nir - red) / (nir + red + 0.5)", "YlGn"),
        ("NDWI", ["B03", "B08"], "(green - nir) / (green + nir)", "Blues"),
        ("NDMI", ["B08", "B11"], "(nir - swir) / (nir + swir)", "BrBG"),
        ("NDBI", ["B11", "B08"], "(swir - nir) / (swir + nir)", "Oranges"),
        ("NBR", ["B08", "B12"], "(nir - swir2) / (nir + swir2)", "RdYlGn"),
    ],
)
def test_get_index_config_returns_common_sentinel2_indices(
    index_name,
    required_bands,
    formula,
    colormap,
):
    config = get_index_config(index_name.lower())

    assert config.name == index_name
    assert config.required_bands == required_bands
    assert config.index_formula == formula
    assert config.render_config.colormap == colormap


def test_registered_sentinel2_indices_use_known_band_assets():
    source_config = get_raster_prepare_data_source_config("sentinel2")

    for index_config in INDEX_REGISTRY.values():
        index_source = index_config.data_sources.get("sentinel2")
        if index_source is None:
            continue

        for band in index_source.required_bands:
            assert band in source_config.band_assets


def test_resolve_raster_product_config_returns_sentinel2_ndvi():
    config = resolve_raster_product_config("NDVI", "sentinel2")

    assert config.index_name == "NDVI"
    assert config.data_source == "sentinel2"
    assert config.required_bands == ["B04", "B08"]
    assert config.band_roles == {"red": "B04", "nir": "B08"}
    assert config.render_config.colormap == "greens"
    assert config.provider == "earth_search"
    assert config.collection == "sentinel-2-l2a"
    assert config.band_assets["B04"] == "red"
    assert config.band_assets["B08"] == "nir"
    assert config.enabled_for_raster_prepare is True


def test_resolve_raster_product_config_returns_landsat_ndwi_registry_only():
    config = resolve_raster_product_config("NDWI", "landsat")

    assert config.index_name == "NDWI"
    assert config.data_source == "landsat"
    assert config.required_bands == ["B03", "B05"]
    assert config.band_roles == {"green": "B03", "nir": "B05"}
    assert config.provider == "earth_search"
    assert config.collection == "landsat-c2-l2"
    assert config.band_assets["B03"] == "green"
    assert config.band_assets["B05"] == "nir08"
    assert config.enabled_for_raster_prepare is False


def test_resolve_raster_product_config_returns_sentinel2_ndmi():
    config = resolve_raster_product_config("NDMI", "sentinel2")

    assert config.index_name == "NDMI"
    assert config.data_source == "sentinel2"
    assert config.required_bands == ["B08", "B11"]
    assert config.band_roles == {"nir": "B08", "swir": "B11"}
    assert config.index_formula == "(nir - swir) / (nir + swir)"
    assert config.band_assets["B11"] == "swir16"
    assert config.enabled_for_raster_prepare is True


def test_resolve_raster_product_config_rejects_unsupported_data_source():
    with pytest.raises(ValueError, match="Unsupported raster data source"):
        resolve_raster_product_config("NDVI", "modis")


def test_get_raster_prepare_data_source_config_rejects_landsat_for_v1():
    # Landsat 已登记在 registry，但 V1 raster_prepare 暂时不执行该数据源。
    with pytest.raises(ValueError, match="V1 raster prepare supports"):
        get_raster_prepare_data_source_config("landsat")


def test_get_raster_data_source_config_returns_landsat_registry_config():
    config = get_raster_data_source_config("landsat")

    assert config.name == "landsat"
    assert config.enabled_for_raster_prepare is False


def test_get_index_config_rejects_unsupported_index():
    with pytest.raises(ValueError, match="Unsupported index"):
        get_index_config("NOPE")
