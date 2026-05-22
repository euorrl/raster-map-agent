import pytest

from app.registry import get_index_config


def test_get_index_config_returns_ndvi_config():
    # 验证 registry 可以返回 NDVI 的波段和公式配置。
    config = get_index_config("ndvi")

    assert config.name == "NDVI"
    assert config.required_bands == ["B04", "B08"]
    assert config.index_formula == "(nir - red) / (nir + red)"


def test_get_index_config_rejects_unsupported_index():
    # 验证不支持的指数会抛出清晰错误。
    with pytest.raises(ValueError, match="Unsupported index"):
        get_index_config("NOPE")
