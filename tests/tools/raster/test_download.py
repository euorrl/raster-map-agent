from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.raster import (
    RasterDownloadError,
    RasterDownloadRequest,
    RasterScene,
    download_raster_bands,
)
from app.tools.raster.download import _search_earth_search


def test_download_raster_bands_selects_lowest_cloud_scene(monkeypatch, tmp_path):
    # 验证工具会选择云量最低的 scene，并下载所需波段。
    scenes = [
        RasterScene(
            scene_id="scene_high_cloud",
            cloud_cover=30,
            assets={
                "red": "https://example.com/high_red.tif",
                "nir": "https://example.com/high_nir.tif",
            },
        ),
        RasterScene(
            scene_id="scene_low_cloud",
            cloud_cover=5,
            assets={
                "red": "https://example.com/low_red.tif",
                "nir": "https://example.com/low_nir.tif",
            },
        ),
    ]

    monkeypatch.setattr(
        "app.tools.raster.download._search_earth_search",
        lambda _: scenes,
    )
    monkeypatch.setattr(
        "app.tools.raster.download._download_asset",
        _write_mock_asset,
    )

    request = RasterDownloadRequest(
        bbox=[9.04, 45.35, 9.32, 45.56],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["b04", "b08"],
        output_dir=tmp_path,
    )

    result = download_raster_bands(request)

    assert result.selected_scene == "scene_low_cloud"
    assert set(result.band_paths) == {"B04", "B08"}
    assert Path(result.band_paths["B04"]).exists()
    assert Path(result.band_paths["B08"]).exists()


def test_download_raster_bands_rejects_empty_search_result(monkeypatch, tmp_path):
    # 验证没有候选 scene 时会抛出下载错误。
    monkeypatch.setattr(
        "app.tools.raster.download._search_earth_search",
        lambda _: [],
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="No raster scenes found"):
        download_raster_bands(request)


def test_download_raster_bands_rejects_missing_asset(monkeypatch, tmp_path):
    # 验证候选 scene 缺少所需波段 asset 时会抛出下载错误。
    scenes = [
        RasterScene(
            scene_id="scene_missing_nir",
            cloud_cover=5,
            assets={"red": "https://example.com/red.tif"},
        )
    ]
    monkeypatch.setattr(
        "app.tools.raster.download._search_earth_search",
        lambda _: scenes,
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="missing asset"):
        download_raster_bands(request)


def test_download_raster_bands_filters_cloud_cover(monkeypatch, tmp_path):
    # 验证超过云量阈值的 scene 会在本地过滤掉。
    scenes = [
        RasterScene(
            scene_id="scene_too_cloudy",
            cloud_cover=80,
            assets={
                "red": "https://example.com/red.tif",
                "nir": "https://example.com/nir.tif",
            },
        )
    ]
    monkeypatch.setattr(
        "app.tools.raster.download._search_earth_search",
        lambda _: scenes,
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="No raster scenes found"):
        download_raster_bands(request)


def test_raster_download_request_rejects_unsupported_band(tmp_path):
    # 验证暂不支持的波段会在请求构建阶段被拒绝。
    with pytest.raises(ValidationError, match="Unsupported raster bands"):
        RasterDownloadRequest(
            bbox=[9.04, 45.35, 9.32, 45.56],
            start_date="2024-06-01",
            end_date="2024-08-31",
            max_cloud_cover=20,
            required_bands=["B99"],
            output_dir=tmp_path,
        )


def test_search_earth_search_uses_rfc3339_datetime(monkeypatch, tmp_path):
    # 验证 STAC 搜索请求会使用 RFC3339 时间范围。
    captured_payload = {}

    def capture_post_json(url, payload):
        captured_payload.update(payload)
        return {"features": []}

    monkeypatch.setattr("app.tools.raster.download._post_json", capture_post_json)

    request = _build_request(tmp_path)

    assert _search_earth_search(request) == []
    assert captured_payload["datetime"] == (
        "2024-06-01T00:00:00Z/2024-08-31T23:59:59Z"
    )


def _build_request(output_dir: Path) -> RasterDownloadRequest:
    return RasterDownloadRequest(
        bbox=[9.04, 45.35, 9.32, 45.56],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
        output_dir=output_dir,
    )


def _write_mock_asset(url: str, output_path: Path) -> None:
    output_path.write_text(url, encoding="utf-8")
