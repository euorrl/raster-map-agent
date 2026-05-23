import json

import pytest

from app.tools.raster_prepare import (
    AOIRequest,
    RasterDownloadError,
    resolve_administrative_aoi,
)


def test_resolve_administrative_aoi_downloads_boundary_and_builds_result(
    monkeypatch, tmp_path
):
    """Nominatim 查询应返回目标 GeoJSON、bbox 和尺度。"""

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "bbox": [119.9, 30.1, 120.5, 30.5],
                "properties": {
                    "display_name": "Hangzhou, Zhejiang, China",
                    "category": "boundary",
                    "type": "administrative",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [119.9, 30.1],
                            [120.5, 30.1],
                            [120.5, 30.5],
                            [119.9, 30.5],
                            [119.9, 30.1],
                        ]
                    ],
                },
            }
        ],
    }

    monkeypatch.setattr("app.tools.raster_prepare.aoi._get_json", lambda _url: geojson)

    result = resolve_administrative_aoi(
        AOIRequest(
            query="Hangzhou, Zhejiang, China",
            output_dir=tmp_path,
        )
    )

    assert result.name == "Hangzhou, Zhejiang, China"
    assert result.bbox == [119.9, 30.1, 120.5, 30.5]
    assert result.area_km2 > 0
    assert result.spatial_scale == "local"
    assert result.source == "nominatim"
    assert result.boundary_geojson_path.endswith("Hangzhou_Zhejiang_China.geojson")

    selected_geojson = json.loads(
        tmp_path.joinpath("Hangzhou_Zhejiang_China.geojson").read_text(encoding="utf-8")
    )
    assert selected_geojson["features"][0]["properties"]["type"] == "administrative"


def test_resolve_administrative_aoi_raises_when_no_polygon_boundary(
    monkeypatch, tmp_path
):
    """如果候选结果没有 polygon，应显式失败。"""

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"display_name": "Hangzhou, Zhejiang, China"},
                "geometry": {"type": "Point", "coordinates": [120.2, 30.3]},
            }
        ],
    }

    monkeypatch.setattr("app.tools.raster_prepare.aoi._get_json", lambda _url: geojson)

    with pytest.raises(RasterDownloadError, match="AOI boundary not found"):
        resolve_administrative_aoi(
            AOIRequest(
                query="Hangzhou, Zhejiang, China",
                output_dir=tmp_path,
            )
        )


def test_resolve_administrative_aoi_uses_geometry_bbox_when_bbox_missing(
    monkeypatch, tmp_path
):
    """没有 bbox 字段时，应从 geometry 坐标中计算 bbox。"""

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"display_name": "Test AOI"},
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

    monkeypatch.setattr("app.tools.raster_prepare.aoi._get_json", lambda _url: geojson)

    result = resolve_administrative_aoi(
        AOIRequest(
            query="Test AOI",
            output_dir=tmp_path,
        )
    )

    assert result.bbox == [2, 4, 6, 8]
