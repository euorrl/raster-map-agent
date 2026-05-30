from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from app.registry import INDEX_REGISTRY  # noqa: E402
from app.tools.render_preview import (  # noqa: E402
    RenderPreviewError,
    RenderPreviewRequest,
    render_index_preview,
)
from app.tools.render_preview.render import (  # noqa: E402
    SUPPORTED_COLORMAPS,
    _apply_colormap,
    _get_preview_shape,
)


def test_render_preview_request_uses_index_tif_parent_as_output_dir(tmp_path):
    request = RenderPreviewRequest(
        index_name="ndvi",
        index_tif_path=tmp_path / "output" / "result.tif",
    )

    assert request.index_name == "NDVI"
    assert request.output_path == tmp_path / "output" / "preview.png"


def test_render_preview_request_allows_custom_output_filename(tmp_path):
    request = RenderPreviewRequest(
        index_name="NDWI",
        index_tif_path=tmp_path / "output" / "result.tif",
        output_filename="water_preview.png",
    )

    assert request.output_path == Path(tmp_path / "output" / "water_preview.png")


def test_render_preview_request_has_default_max_size(tmp_path):
    request = RenderPreviewRequest(
        index_name="NDVI",
        index_tif_path=tmp_path / "output" / "result.tif",
    )

    assert request.max_size == 2048
    assert request.include_colorbar is True


def test_render_index_preview_writes_png(tmp_path):
    index_tif_path = tmp_path / "output" / "result.tif"
    index_tif_path.parent.mkdir()
    _write_index_raster(
        index_tif_path,
        _make_preview_test_data(),
    )

    result = render_index_preview(
        RenderPreviewRequest(index_name="NDVI", index_tif_path=index_tif_path)
    )

    assert result.preview_path == str(tmp_path / "output" / "preview.png")
    with rasterio.open(result.preview_path) as dataset:
        assert dataset.driver == "PNG"
        assert dataset.count == 4
        assert dataset.height == 272
        assert dataset.width == 160
        alpha = dataset.read(4)

    assert alpha[0, 0] == 0
    assert alpha[1, 1] == 255
    assert alpha[148, 64] == 255
    assert alpha[-1, -1] == 0


def test_render_index_preview_can_disable_colorbar(tmp_path):
    index_tif_path = tmp_path / "output" / "result.tif"
    index_tif_path.parent.mkdir()
    _write_index_raster(index_tif_path, np.ones((2, 2), dtype="float32"))

    result = render_index_preview(
        RenderPreviewRequest(
            index_name="NDWI",
            index_tif_path=index_tif_path,
            include_colorbar=False,
        )
    )

    with rasterio.open(result.preview_path) as dataset:
        assert dataset.height == 2
        assert dataset.width == 2


def test_apply_colormap_rejects_unknown_colormap():
    with pytest.raises(RenderPreviewError, match="Unsupported render colormap"):
        _apply_colormap(
            scaled=np.ones((2, 2), dtype="float32"),
            valid_mask=np.ones((2, 2), dtype="bool"),
            colormap="unknown",
        )


def test_render_preview_supports_registered_colormaps():
    registered_colormaps = {
        index_config.render_config.colormap for index_config in INDEX_REGISTRY.values()
    }

    for colormap in registered_colormaps:
        rgba = _apply_colormap(
            scaled=np.ones((2, 2), dtype="float32"),
            valid_mask=np.ones((2, 2), dtype="bool"),
            colormap=colormap,
        )

        assert colormap.lower() in SUPPORTED_COLORMAPS
        assert rgba.shape == (4, 2, 2)
        assert np.all(rgba[3] == 255)


def test_get_preview_shape_limits_longest_side():
    assert _get_preview_shape(height=1000, width=2000, max_size=500) == (250, 500)
    assert _get_preview_shape(height=100, width=200, max_size=500) == (100, 200)


def _write_index_raster(path, data):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(data.astype("float32"), 1)


def _make_preview_test_data():
    data = np.linspace(-0.2, 0.8, 120 * 160, dtype="float32").reshape(120, 160)
    data[0, 0] = -9999.0
    return data
