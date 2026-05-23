import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.tools.raster_prepare import (
    RasterClipError,
    RasterClipRequest,
    clip_raster_to_aoi,
)


def test_clip_raster_to_aoi_writes_clipped_geotiff(tmp_path):
    """单个 raster 应能按 GeoJSON 边界裁剪成新的 GeoTIFF。"""

    raster_path = tmp_path / "source.tif"
    geojson_path = tmp_path / "aoi.geojson"
    output_path = tmp_path / "clipped_raster" / "clipped.tif"

    _write_test_raster(raster_path)
    _write_test_geojson(geojson_path)

    result = clip_raster_to_aoi(
        RasterClipRequest(
            raster_path=raster_path,
            boundary_geojson_path=geojson_path,
            workspace_dir=tmp_path,
            output_filename="clipped.tif",
        )
    )

    assert result.clipped_raster_path == str(output_path)
    assert output_path.exists()

    with rasterio.open(output_path) as clipped:
        assert clipped.count == 1
        assert clipped.width == 4
        assert clipped.height == 4
        assert clipped.crs.to_string() == "EPSG:4326"
        assert clipped.dtypes[0] == "float32"
        assert clipped.nodatavals[0] == -9999.0
        assert (clipped.read(1) == -9999.0).sum() == 0


def test_clip_raster_to_aoi_fills_pixels_outside_aoi_with_nodata(tmp_path):
    """AOI 外但仍在裁剪外接矩形内的像素应被写为 nodata。"""

    raster_path = tmp_path / "source.tif"
    geojson_path = tmp_path / "aoi.geojson"
    output_path = tmp_path / "clipped_raster" / "source_clipped.tif"

    _write_test_raster(raster_path)
    _write_triangle_geojson(geojson_path)

    clip_raster_to_aoi(
        RasterClipRequest(
            raster_path=raster_path,
            boundary_geojson_path=geojson_path,
            workspace_dir=tmp_path,
        )
    )

    with rasterio.open(output_path) as clipped:
        data = clipped.read(1)

    assert data.dtype == "float32"
    assert (data == -9999.0).sum() > 0


def test_clip_raster_to_aoi_rejects_missing_raster(tmp_path):
    """输入 raster 不存在时应显式失败。"""

    geojson_path = tmp_path / "aoi.geojson"
    _write_test_geojson(geojson_path)

    with pytest.raises(RasterClipError, match="Input raster does not exist"):
        clip_raster_to_aoi(
            RasterClipRequest(
                raster_path=tmp_path / "missing.tif",
                boundary_geojson_path=geojson_path,
                workspace_dir=tmp_path,
            )
        )


def _write_test_raster(path):
    data = np.arange(100, dtype="uint16").reshape((1, 10, 10))
    transform = from_origin(0, 10, 1, 1)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(data)


def _write_test_geojson(path):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "test"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [2, 4],
                            [6, 4],
                            [6, 8],
                            [2, 8],
                            [2, 4],
                        ]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(geojson), encoding="utf-8")


def _write_triangle_geojson(path):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "triangle"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [2, 4],
                            [6, 4],
                            [2, 8],
                            [2, 4],
                        ]
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(geojson), encoding="utf-8")
