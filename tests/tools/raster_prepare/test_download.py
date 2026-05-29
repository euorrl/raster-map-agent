from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from app.tools.raster_prepare import (
    RasterDownloadAsset,
    RasterDownloadError,
    RasterDownloadRequest,
    RasterScene,
    RasterSceneCandidateStore,
    RasterScenePlanDiagnostics,
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
            diagnostics=RasterScenePlanDiagnostics(
                coverage_status="covered",
                coverage_ratio=1,
                min_coverage_ratio=1,
                is_retriable=False,
                message=(
                    "Selected scenes cover 100.00% of the AOI geometry, "
                    "meeting the minimum required coverage 100.00%."
                ),
                selected_scene_count=2,
            ),
            data_source="sentinel2",
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


def test_build_raster_scene_plan_returns_retryable_empty_search_result(
    monkeypatch,
    tmp_path,
):
    # 验证没有候选 scene 时返回可重试诊断，而不是直接抛出错误。
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: [],
    )

    request = _build_request(tmp_path)

    plan = build_raster_scene_plan(request)

    assert plan.scene_ids == []
    assert plan.assets == []
    assert plan.diagnostics.coverage_status == "not_covered"
    assert plan.diagnostics.coverage_ratio == 0
    assert plan.diagnostics.is_retriable is True
    assert plan.diagnostics.failure_reason == "no_raster_scenes_found"
    assert plan.diagnostics.suggested_actions == [
        "expand_date_range",
        "increase_max_cloud_cover",
    ]
    assert plan.diagnostics.selected_scene_count == 0


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


def test_build_raster_scene_plan_returns_retryable_when_cloud_filter_removes_all(
    monkeypatch,
    tmp_path,
):
    # 验证超过云量阈值的 scene 被过滤后会返回可重试诊断。
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

    plan = build_raster_scene_plan(request)

    assert plan.scene_ids == []
    assert plan.assets == []
    assert plan.diagnostics.coverage_status == "not_covered"
    assert plan.diagnostics.coverage_ratio == 0
    assert plan.diagnostics.is_retriable is True
    assert plan.diagnostics.failure_reason == "no_raster_scenes_found"


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


def test_raster_scene_plan_request_rejects_unsupported_data_source():
    # 验证 V1 只接受已经登记的数据源，避免上游传入不可执行的卫星类型。
    with pytest.raises(ValidationError, match="Unsupported raster data source"):
        RasterScenePlanRequest(
            bbox=[9.04, 45.35, 9.32, 45.56],
            start_date="2024-06-01",
            end_date="2024-08-31",
            max_cloud_cover=20,
            required_bands=["B04"],
            data_source="landsat",
        )


def test_raster_scene_plan_request_normalizes_data_source_name():
    # 验证上游大小写不同也会被统一成 V1 支持的 sentinel2。
    request = RasterScenePlanRequest(
        bbox=[9.04, 45.35, 9.32, 45.56],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04"],
        data_source="Sentinel2",
    )

    assert request.data_source == "sentinel2"


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


def test_build_raster_scene_plan_uses_cloud_cover_for_similar_contribution(
    monkeypatch, tmp_path
):
    # 验证新增覆盖贡献接近时，优先选择云量更低的 scene。
    scenes = [
        _build_scene("S2A_32TMR_20240801_0_L2A", 12, _polygon(0, 0, 5, 10)),
        _build_scene("S2A_32TMR_20240802_0_L2A", 1, _polygon(0, 0, 5, 10)),
        _build_scene("S2A_32TNR_20240801_0_L2A", 6, _polygon(5, 0, 10, 10)),
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    store = RasterSceneCandidateStore()
    request = RasterScenePlanRequest(
        bbox=[0, 0, 10, 10],
        boundary_geojson_path=_write_geojson(tmp_path, _polygon(0, 0, 10, 10)),
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=50,
        required_bands=["B04", "B08"],
        max_selected_scenes=5,
    )

    plan = build_raster_scene_plan(request, store=store)

    assert set(store.scenes) == {
        "S2A_32TMR_20240801_0_L2A",
        "S2A_32TMR_20240802_0_L2A",
        "S2A_32TNR_20240801_0_L2A",
    }
    assert plan.scene_ids == [
        "S2A_32TMR_20240802_0_L2A",
        "S2A_32TNR_20240801_0_L2A",
    ]


def test_build_raster_scene_plan_prefers_uncovered_area_over_lower_cloud(
    monkeypatch, tmp_path
):
    # 验证已覆盖区域内的低云量 scene 不会挤掉能补足缺口的 scene。
    scenes = [
        _build_scene("S2A_32TMR_20240801_0_L2A", 1, _polygon(0, 0, 5, 10)),
        _build_scene("S2A_32TMR_20240802_0_L2A", 2, _polygon(0, 0, 5, 10)),
        _build_scene("S2A_32TNR_20240801_0_L2A", 15, _polygon(5, 0, 10, 10)),
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    request = RasterScenePlanRequest(
        bbox=[0, 0, 10, 10],
        boundary_geojson_path=_write_geojson(tmp_path, _polygon(0, 0, 10, 10)),
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=50,
        required_bands=["B04", "B08"],
        max_selected_scenes=2,
    )

    plan = build_raster_scene_plan(request)

    assert plan.scene_ids == [
        "S2A_32TMR_20240801_0_L2A",
        "S2A_32TNR_20240801_0_L2A",
    ]
    assert plan.diagnostics.coverage_status == "covered"


def test_build_raster_scene_plan_accumulates_existing_store(monkeypatch, tmp_path):
    # 验证传入同一个 store 时，多次调用会累积不同时间窗口的候选 scene。
    search_results = [
        [_build_scene("S2A_32TMR_20240801_0_L2A", 10)],
        [
            _build_scene("S2A_32TMR_20240701_0_L2A", 5),
            _build_scene("S2A_32TNR_20240701_0_L2A", 7),
        ],
    ]

    def search_once(_request):
        return search_results.pop(0)

    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        search_once,
    )
    store = RasterSceneCandidateStore()
    request = _build_request(tmp_path)

    build_raster_scene_plan(request, store=store)
    plan = build_raster_scene_plan(request, store=store)

    assert set(store.scenes) == {
        "S2A_32TMR_20240801_0_L2A",
        "S2A_32TNR_20240701_0_L2A",
        "S2A_32TMR_20240701_0_L2A",
    }
    assert plan.scene_ids == ["S2A_32TMR_20240701_0_L2A"]


def test_build_raster_scene_plan_marks_covered_scene_plan(monkeypatch, tmp_path):
    # 验证选中的 scene footprint 完整覆盖真实 AOI 时，诊断结果为 covered。
    scenes = [_build_scene("S2A_32TMR_20240801_0_L2A", 5, _polygon(0, 0, 10, 10))]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    request = _build_request(tmp_path, bbox=[0, 0, 10, 10])

    plan = build_raster_scene_plan(request)

    assert plan.diagnostics.coverage_status == "covered"
    assert plan.diagnostics.coverage_ratio == pytest.approx(1)
    assert plan.diagnostics.is_retriable is False
    assert plan.diagnostics.failure_reason is None


def test_build_raster_scene_plan_detects_footprint_gap(monkeypatch, tmp_path):
    # 验证 coverage 使用真实 AOI 和 scene footprint union。
    scenes = [
        _build_scene("S2A_32TMR_20240801_0_L2A", 5, _polygon(0, 0, 4, 10)),
        _build_scene("S2A_32TMR_20240802_0_L2A", 6, _polygon(6, 0, 10, 10)),
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    request = _build_request(
        tmp_path,
        bbox=[0, 0, 10, 10],
        min_coverage_ratio=0.9,
    )

    plan = build_raster_scene_plan(request)

    assert plan.diagnostics.coverage_status == "not_covered"
    assert plan.diagnostics.coverage_ratio == pytest.approx(0.8)
    assert plan.diagnostics.min_coverage_ratio == pytest.approx(0.9)
    assert plan.diagnostics.is_retriable is True
    assert plan.diagnostics.failure_reason == "insufficient_spatial_coverage"
    assert plan.diagnostics.suggested_actions == [
        "expand_date_range",
        "increase_max_cloud_cover",
    ]


def test_build_raster_scene_plan_accepts_coverage_above_threshold(
    monkeypatch, tmp_path
):
    scenes = [
        _build_scene("S2A_32TMR_20240801_0_L2A", 5, _polygon(0, 0, 4, 10)),
        _build_scene("S2A_32TMR_20240802_0_L2A", 6, _polygon(6, 0, 10, 10)),
    ]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    request = _build_request(
        tmp_path,
        bbox=[0, 0, 10, 10],
        min_coverage_ratio=0.7,
    )

    plan = build_raster_scene_plan(request)

    assert plan.diagnostics.coverage_status == "covered"
    assert plan.diagnostics.coverage_ratio == pytest.approx(0.8)
    assert plan.diagnostics.min_coverage_ratio == pytest.approx(0.7)
    assert plan.diagnostics.is_retriable is False
    assert plan.diagnostics.failure_reason is None
    assert plan.diagnostics.suggested_actions == []


def test_build_raster_scene_plan_reports_missing_aoi_geometry(monkeypatch, tmp_path):
    scenes = [_build_scene("S2A_32TMR_20240801_0_L2A", 5, _polygon(0, 0, 10, 10))]
    monkeypatch.setattr(
        "app.tools.raster_prepare.scene_plan._search_earth_search",
        lambda _: scenes,
    )
    request = _build_request(tmp_path, bbox=[0, 0, 10, 10], include_boundary=False)

    plan = build_raster_scene_plan(request)

    assert plan.diagnostics.coverage_status == "unknown"
    assert plan.diagnostics.coverage_ratio == 0
    assert plan.diagnostics.failure_reason == "missing_aoi_geometry"
    assert plan.diagnostics.is_retriable is False
    assert plan.diagnostics.suggested_actions == []


def test_build_raster_scene_plan_reports_missing_geometry(monkeypatch, tmp_path):
    # 验证缺少 footprint geometry 时，返回可供 ReAct 使用的 unknown 诊断。
    scenes = [
        RasterScene(
            scene_id="S2A_32TMR_20240801_0_L2A",
            cloud_cover=5,
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

    plan = build_raster_scene_plan(_build_request(tmp_path))

    assert plan.diagnostics.coverage_status == "unknown"
    assert plan.diagnostics.failure_reason == "missing_scene_geometry"
    assert plan.diagnostics.is_retriable is False
    assert plan.diagnostics.suggested_actions == []
    assert plan.diagnostics.missing_geometry_scene_ids == ["S2A_32TMR_20240801_0_L2A"]


def _build_request(
    _workspace_dir: Path,
    bbox: list[float] | None = None,
    include_boundary: bool = True,
    min_coverage_ratio: float = 0.7,
) -> RasterScenePlanRequest:
    bbox = bbox or [9.04, 45.35, 9.32, 45.56]
    boundary_geojson_path = None
    if include_boundary:
        boundary_geojson_path = _write_geojson(_workspace_dir, _polygon(*bbox))

    return RasterScenePlanRequest(
        bbox=bbox,
        boundary_geojson_path=boundary_geojson_path,
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
        min_coverage_ratio=min_coverage_ratio,
    )


def _build_scene(
    scene_id: str,
    cloud_cover: float,
    geometry: dict | None = None,
) -> RasterScene:
    if geometry is None:
        geometry = _polygon(9, 45, 10, 46)

    return RasterScene(
        scene_id=scene_id,
        cloud_cover=cloud_cover,
        bbox=geometry["coordinates"][0][0] + geometry["coordinates"][0][2],
        geometry=geometry,
        assets={
            "red": f"https://example.com/{scene_id}_red.tif",
            "nir": f"https://example.com/{scene_id}_nir.tif",
        },
    )


def _polygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }


def _write_geojson(tmp_path: Path, geometry: dict) -> Path:
    path = tmp_path / "aoi.geojson"
    geojson = {"type": "Feature", "properties": {}, "geometry": geometry}
    path.write_text(json.dumps(geojson), encoding="utf-8")
    return path


def _write_mock_asset(url: str, output_path: Path) -> None:
    output_path.write_text(url, encoding="utf-8")
