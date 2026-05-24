from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.raster_prepare import (
    RasterDownloadAsset,
    RasterDownloadError,
    RasterDownloadRequest,
    RasterScene,
    RasterScenePlanResult,
    RasterScenePlanRequest,
    build_raster_scene_plan,
    download_raster_assets,
)
from app.tools.raster_prepare.scene_plan import _search_earth_search


def test_download_raster_assets_downloads_planned_assets(monkeypatch, tmp_path):
    # 验证 download 只按给定 plan 下载 asset，不负责 scene 选择。
    monkeypatch.setattr(
        "app.tools.raster_prepare.download._download_asset",
        _write_mock_asset,
    )

    request = RasterDownloadRequest(
        plan=RasterScenePlanResult(
            scene_ids=["scene_low_cloud", "scene_medium_cloud"],
            assets=[
                RasterDownloadAsset(
                    scene_id="scene_low_cloud",
                    band="B04",
                    url="https://example.com/low_red.tif",
                ),
                RasterDownloadAsset(
                    scene_id="scene_low_cloud",
                    band="B08",
                    url="https://example.com/low_nir.tif",
                ),
                RasterDownloadAsset(
                    scene_id="scene_medium_cloud",
                    band="B04",
                    url="https://example.com/medium_red.tif",
                ),
                RasterDownloadAsset(
                    scene_id="scene_medium_cloud",
                    band="B08",
                    url="https://example.com/medium_nir.tif",
                ),
            ],
            provider="earth_search",
            collection="sentinel-2-l2a",
        ),
        workspace_dir=tmp_path,
    )

    result = download_raster_assets(request)

    assert result.scene_ids == ["scene_low_cloud", "scene_medium_cloud"]
    assert set(result.band_paths) == {"B04", "B08"}
    assert len(result.band_paths["B04"]) == 2
    assert len(result.band_paths["B08"]) == 2
    assert all(Path(path).exists() for path in result.band_paths["B04"])
    assert all(Path(path).exists() for path in result.band_paths["B08"])


def test_build_raster_scene_plan_rejects_empty_search_result(monkeypatch, tmp_path):
    # 验证没有候选 scene 时会抛出下载错误。
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: [],
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="No raster scenes found"):
        build_raster_scene_plan(request)


def test_build_raster_scene_plan_rejects_missing_asset(monkeypatch, tmp_path):
    # 验证候选 scene 缺少所需波段 asset 时会抛出下载错误。
    scenes = [
        RasterScene(
            scene_id="scene_missing_nir",
            cloud_cover=5,
            assets={"red": "https://example.com/red.tif"},
        )
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="missing asset"):
        build_raster_scene_plan(request)


def test_build_raster_scene_plan_filters_cloud_cover(monkeypatch, tmp_path):
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
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )

    request = _build_request(tmp_path)

    with pytest.raises(RasterDownloadError, match="No raster scenes found"):
        build_raster_scene_plan(request)


def test_raster_scene_plan_request_rejects_unsupported_band():
    # 验证暂不支持的波段会在请求构建阶段被拒绝。
    with pytest.raises(ValidationError, match="Unsupported raster bands"):
        RasterScenePlanRequest(
            bbox=[9.04, 45.35, 9.32, 45.56],
            start_date="2024-06-01",
            end_date="2024-08-31",
            max_cloud_cover=20,
            required_bands=["B99"],
        )


def test_search_earth_search_uses_rfc3339_datetime(monkeypatch, tmp_path):
    # 验证 STAC 搜索请求会使用 RFC3339 时间范围。
    captured_payload = {}

    def capture_post_json(url, payload):
        captured_payload.update(payload)
        return {"features": []}

    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._post_json", capture_post_json
    )

    request = _build_request(tmp_path)

    assert _search_earth_search(request) == []
    assert captured_payload["datetime"] == ("2024-06-01T00:00:00Z/2024-08-31T23:59:59Z")


def test_build_raster_scene_plan_deduplicates_scenes(monkeypatch, tmp_path):
    # 验证 scene plan 会按 scene_id 去重，避免重复下载同一个 scene。
    scenes = [
        RasterScene(
            scene_id="scene_same",
            cloud_cover=5,
            assets={
                "red": "https://example.com/first_red.tif",
                "nir": "https://example.com/first_nir.tif",
            },
        ),
        RasterScene(
            scene_id="scene_same",
            cloud_cover=5,
            assets={
                "red": "https://example.com/second_red.tif",
                "nir": "https://example.com/second_nir.tif",
            },
        ),
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )

    plan = build_raster_scene_plan(_build_request(tmp_path))

    assert plan.scene_ids == ["scene_same"]
    assert len(plan.assets) == 2
    assert {asset.band for asset in plan.assets} == {"B04", "B08"}
    assert {asset.url for asset in plan.assets} == {
        "https://example.com/first_red.tif",
        "https://example.com/first_nir.tif",
    }


def _build_request(_workspace_dir: Path) -> RasterScenePlanRequest:
    return RasterScenePlanRequest(
        bbox=[9.04, 45.35, 9.32, 45.56],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
    )


def _write_mock_asset(url: str, output_path: Path) -> None:
    output_path.write_text(url, encoding="utf-8")
