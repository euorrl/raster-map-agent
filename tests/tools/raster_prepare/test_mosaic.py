import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from app.tools.raster_prepare import (  # noqa: E402
    RasterMosaicError,
    RasterMosaicRequest,
    mosaic_rasters_by_band,
)


def test_mosaic_rasters_by_band_groups_and_writes_outputs(tmp_path):
    """输入目录中的 tif 应按 band 分组，并分别输出 mosaic tif。"""

    input_dir = tmp_path / "raster"
    output_dir = tmp_path / "mosaic_raster"
    input_dir.mkdir()

    _write_test_raster(
        input_dir / "scene_left_B04.tif",
        np.full((2, 2), 1, dtype="uint16"),
        from_origin(0, 2, 1, 1),
    )
    _write_test_raster(
        input_dir / "scene_right_B04.tif",
        np.full((2, 2), 2, dtype="uint16"),
        from_origin(2, 2, 1, 1),
    )
    _write_test_raster(
        input_dir / "scene_left_B08.tif",
        np.full((2, 2), 8, dtype="uint16"),
        from_origin(0, 2, 1, 1),
    )

    result = mosaic_rasters_by_band(
        RasterMosaicRequest(
            input_dir=input_dir,
            output_dir=output_dir,
        )
    )

    assert set(result.band_paths) == {"B04", "B08"}
    assert result.band_paths["B04"] == str(output_dir / "mosaic_B04.tif")
    assert result.band_paths["B08"] == str(output_dir / "mosaic_B08.tif")

    with rasterio.open(result.band_paths["B04"]) as mosaic:
        data = mosaic.read(1)

    assert data.shape == (2, 4)
    assert data.tolist() == [
        [1, 1, 2, 2],
        [1, 1, 2, 2],
    ]


def test_mosaic_rasters_by_band_uses_first_value_in_overlap(tmp_path):
    """重叠区域应保留排序后第一张 tif 的像素值。"""

    input_dir = tmp_path / "raster"
    output_dir = tmp_path / "mosaic_raster"
    input_dir.mkdir()

    _write_test_raster(
        input_dir / "a_scene_B04.tif",
        np.full((2, 2), 1, dtype="uint16"),
        from_origin(0, 2, 1, 1),
    )
    _write_test_raster(
        input_dir / "b_scene_B04.tif",
        np.full((2, 2), 9, dtype="uint16"),
        from_origin(0, 2, 1, 1),
    )

    result = mosaic_rasters_by_band(
        RasterMosaicRequest(
            input_dir=input_dir,
            output_dir=output_dir,
        )
    )

    with rasterio.open(result.band_paths["B04"]) as mosaic:
        data = mosaic.read(1)

    assert data.tolist() == [
        [1, 1],
        [1, 1],
    ]


def test_mosaic_rasters_by_band_reprojects_mismatched_crs(tmp_path):
    """不同 CRS 的输入 tif 应被临时重投影后再合并。"""

    input_dir = tmp_path / "raster"
    output_dir = tmp_path / "mosaic_raster"
    input_dir.mkdir()

    _write_test_raster(
        input_dir / "a_scene_wgs84_B04.tif",
        np.full((2, 2), 1, dtype="uint16"),
        from_origin(0, 2, 1, 1),
        crs="EPSG:4326",
    )
    _write_test_raster(
        input_dir / "b_scene_web_mercator_B04.tif",
        np.full((2, 2), 2, dtype="uint16"),
        from_origin(0, 222684, 111342, 111342),
        crs="EPSG:3857",
    )

    result = mosaic_rasters_by_band(
        RasterMosaicRequest(
            input_dir=input_dir,
            output_dir=output_dir,
        )
    )

    with rasterio.open(result.band_paths["B04"]) as mosaic:
        assert mosaic.crs.to_string() == "EPSG:4326"
        assert mosaic.width > 0
        assert mosaic.height > 0


def test_mosaic_rasters_by_band_rejects_empty_input_dir(tmp_path):
    """输入目录没有 GeoTIFF 时应显式失败。"""

    input_dir = tmp_path / "raster"
    output_dir = tmp_path / "mosaic_raster"
    input_dir.mkdir()

    with pytest.raises(RasterMosaicError, match="No GeoTIFF files found"):
        mosaic_rasters_by_band(
            RasterMosaicRequest(
                input_dir=input_dir,
                output_dir=output_dir,
            )
        )


def _write_test_raster(path, data, transform, crs="EPSG:4326"):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
    ) as dataset:
        dataset.write(data, 1)
