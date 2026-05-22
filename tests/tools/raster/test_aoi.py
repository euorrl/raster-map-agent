import json

import pytest

from app.tools.raster import AOIRequest, RasterDownloadError, resolve_administrative_aoi


def test_resolve_administrative_aoi_downloads_boundary_and_builds_result(
    monkeypatch, tmp_path
):
    """行政区请求应返回边界文件路径、目标 GeoJSON、bbox 和尺度。"""

    metadata = {
        "staticDownloadLink": "https://example.com/ITA_ADM2.zip",
        "gjDownloadURL": "https://example.com/ITA_ADM2.geojson",
    }
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"shapeName": "Milano"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [9.04, 45.35],
                            [9.32, 45.35],
                            [9.32, 45.56],
                            [9.04, 45.56],
                            [9.04, 45.35],
                        ]
                    ],
                },
            }
        ],
    }

    def fake_get_json(url):
        if url.endswith("/gbOpen/ITA/ADM2/"):
            return metadata

        return geojson

    monkeypatch.setattr("app.tools.raster.aoi._get_json", fake_get_json)

    result = resolve_administrative_aoi(
        AOIRequest(
            name="Milano",
            iso3="ita",
            admin_level="adm2",
            output_dir=tmp_path,
        )
    )

    assert result.name == "Milano"
    assert result.iso3 == "ITA"
    assert result.admin_level == "ADM2"
    assert result.bbox == [9.04, 45.35, 9.32, 45.56]
    assert result.area_km2 > 0
    assert result.spatial_scale == "local"
    assert result.source == "geoBoundaries"
    assert result.boundary_geojson_path.endswith("Milano_ITA_ADM2.geojson")

    selected_geojson = json.loads(
        tmp_path.joinpath("Milano_ITA_ADM2.geojson").read_text()
    )
    assert selected_geojson["features"][0]["properties"]["shapeName"] == "Milano"


def test_resolve_administrative_aoi_raises_when_boundary_missing(monkeypatch, tmp_path):
    """如果行政区名称匹配不到，应显式失败。"""

    monkeypatch.setattr(
        "app.tools.raster.aoi._get_json",
        lambda _url: {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"shapeName": "Roma"},
                    "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
                }
            ],
            "staticDownloadLink": "https://example.com/ITA_ADM2.zip",
            "gjDownloadURL": "https://example.com/ITA_ADM2.geojson",
        },
    )
    with pytest.raises(RasterDownloadError, match="AOI boundary not found"):
        resolve_administrative_aoi(
            AOIRequest(
                name="Milano",
                iso3="ITA",
                admin_level="ADM2",
                output_dir=tmp_path,
            )
        )


def test_resolve_administrative_aoi_raises_when_metadata_url_missing(tmp_path):
    """如果 geoBoundaries 元数据缺少下载地址，应显式失败。"""

    from app.tools.raster.aoi import _require_metadata_url

    with pytest.raises(RasterDownloadError, match="metadata missing URL"):
        _require_metadata_url({}, "staticDownloadLink")
