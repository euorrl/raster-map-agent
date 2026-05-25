from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.raster_prepare import (
    AOIResult,
    RasterClipResult,
    RasterDownloadResult,
    RasterMosaicResult,
    RasterPrepareRequest,
    RasterScenePlanDiagnostics,
    RasterScenePlanResult,
    prepare_raster_inputs,
)


def test_prepare_raster_inputs_runs_pipeline_and_cleans_intermediates(
    monkeypatch, tmp_path
):
    """prepare 应串联数据准备工具，并在成功后删除中间 raster 目录。"""

    calls = []

    def fake_resolve_aoi(request):
        calls.append(("aoi", request.query))
        boundary_path = request.workspace_dir / "aoi" / "test.geojson"
        boundary_path.parent.mkdir(parents=True)
        boundary_path.write_text("{}", encoding="utf-8")
        return AOIResult(
            name="Test AOI",
            boundary_geojson_path=str(boundary_path),
            bbox=[0, 0, 2, 2],
            area_km2=4,
            source="test",
        )

    def fake_build_scene_plan(request):
        calls.append(
            (
                "scene_plan",
                request.bbox,
                request.boundary_geojson_path,
                request.required_bands,
            )
        )
        return RasterScenePlanResult(
            scene_ids=["scene_1"],
            assets=[],
            diagnostics=RasterScenePlanDiagnostics(
                coverage_status="covered",
                coverage_ratio=1,
                min_coverage_ratio=0.7,
                message="covered",
            ),
            data_source="sentinel2",
            provider="earth_search",
            collection="sentinel-2-l2a",
        )

    def fake_download(request):
        calls.append(("download", request.workspace_dir))
        raster_dir = request.workspace_dir / "raster"
        raster_dir.mkdir()
        (raster_dir / "scene_1_B04.tif").write_text("raw", encoding="utf-8")
        return RasterDownloadResult(
            scene_ids=["scene_1"],
            band_paths={"B04": [str(raster_dir / "scene_1_B04.tif")]},
            data_source="sentinel2",
            provider="earth_search",
            collection="sentinel-2-l2a",
        )

    def fake_mosaic(request):
        calls.append(("mosaic", request.input_dir, request.output_dir))
        request.output_dir.mkdir()
        mosaic_path = request.output_dir / "mosaic_B04.tif"
        mosaic_path.write_text("mosaic", encoding="utf-8")
        return RasterMosaicResult(band_paths={"B04": str(mosaic_path)})

    def fake_clip(request):
        calls.append(("clip", request.raster_path, request.output_path))
        request.output_path.parent.mkdir()
        request.output_path.write_text("clipped", encoding="utf-8")
        return RasterClipResult(
            source_raster_path=str(request.raster_path),
            boundary_geojson_path=str(request.boundary_geojson_path),
            clipped_raster_path=str(request.output_path),
        )

    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.resolve_administrative_aoi",
        fake_resolve_aoi,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.build_raster_scene_plan",
        fake_build_scene_plan,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.download_raster_assets",
        fake_download,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.mosaic_rasters_by_band",
        fake_mosaic,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.clip_raster_to_aoi",
        fake_clip,
    )

    workspace_dir = tmp_path / "run_1"
    result = prepare_raster_inputs(
        RasterPrepareRequest(
            aoi_query="Test City, Test Country",
            start_date="2024-01-01",
            end_date="2024-01-31",
            max_cloud_cover=20,
            index_name="NDVI",
            workspace_dir=workspace_dir,
        )
    )

    workspace_dir = Path(result.workspace_dir)
    assert workspace_dir == tmp_path / "run_1"
    assert result.output_dir == str(workspace_dir / "output")
    assert (workspace_dir / "output").exists()
    assert result.band_paths == {
        "B04": str(workspace_dir / "clipped_raster" / "B04_clipped.tif")
    }
    assert result.index_name == "NDVI"
    assert result.data_source == "sentinel2"
    assert result.required_bands == ["B04", "B08"]
    assert result.band_roles == {"red": "B04", "nir": "B08"}
    assert result.index_formula == "(nir - red) / (nir + red)"
    assert Path(result.band_paths["B04"]).exists()
    assert result.scene_ids == ["scene_1"]
    assert result.diagnostics.coverage_status == "covered"
    assert (workspace_dir / "aoi").exists()
    assert not (workspace_dir / "raster").exists()
    assert not (workspace_dir / "mosaic_raster").exists()
    assert [call[0] for call in calls] == [
        "aoi",
        "scene_plan",
        "download",
        "mosaic",
        "clip",
    ]
    assert calls[1][3] == ["B04", "B08"]


def test_raster_prepare_request_rejects_registry_only_landsat_source(tmp_path):
    with pytest.raises(ValidationError, match="V1 raster prepare supports"):
        RasterPrepareRequest(
            aoi_query="Test City, Test Country",
            index_name="NDVI",
            data_source="landsat",
            start_date="2024-01-01",
            end_date="2024-01-31",
            workspace_dir=tmp_path / "run_1",
        )


def test_raster_prepare_request_accepts_ndwi_sentinel2(tmp_path):
    request = RasterPrepareRequest(
        aoi_query="Test City, Test Country",
        index_name="ndwi",
        data_source="Sentinel2",
        start_date="2024-01-01",
        end_date="2024-01-31",
        workspace_dir=tmp_path / "run_1",
    )

    assert request.index_name == "NDWI"
    assert request.data_source == "sentinel2"


def test_prepare_raster_inputs_uses_index_required_bands(monkeypatch, tmp_path):
    captured_required_bands = []

    def fake_resolve_aoi(request):
        boundary_path = request.workspace_dir / "aoi" / "test.geojson"
        boundary_path.parent.mkdir(parents=True)
        boundary_path.write_text("{}", encoding="utf-8")
        return AOIResult(
            name="Test AOI",
            boundary_geojson_path=str(boundary_path),
            bbox=[0, 0, 2, 2],
            area_km2=4,
            source="test",
        )

    def fake_build_scene_plan(request):
        captured_required_bands.extend(request.required_bands)
        return RasterScenePlanResult(
            scene_ids=["scene_1"],
            assets=[],
            diagnostics=RasterScenePlanDiagnostics(
                coverage_status="covered",
                coverage_ratio=1,
                min_coverage_ratio=0.7,
                message="covered",
            ),
            data_source="sentinel2",
            provider="earth_search",
            collection="sentinel-2-l2a",
        )

    def fake_download(request):
        raster_dir = request.workspace_dir / "raster"
        raster_dir.mkdir()
        return RasterDownloadResult(
            scene_ids=["scene_1"],
            band_paths={},
            data_source="sentinel2",
            provider="earth_search",
            collection="sentinel-2-l2a",
        )

    def fake_mosaic(request):
        request.output_dir.mkdir()
        band_paths = {}
        for band in captured_required_bands:
            mosaic_path = request.output_dir / f"mosaic_{band}.tif"
            mosaic_path.write_text("mosaic", encoding="utf-8")
            band_paths[band] = str(mosaic_path)
        return RasterMosaicResult(band_paths=band_paths)

    def fake_clip(request):
        request.output_path.parent.mkdir(exist_ok=True)
        request.output_path.write_text("clipped", encoding="utf-8")
        return RasterClipResult(
            source_raster_path=str(request.raster_path),
            boundary_geojson_path=str(request.boundary_geojson_path),
            clipped_raster_path=str(request.output_path),
        )

    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.resolve_administrative_aoi",
        fake_resolve_aoi,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.build_raster_scene_plan",
        fake_build_scene_plan,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.download_raster_assets",
        fake_download,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.mosaic_rasters_by_band",
        fake_mosaic,
    )
    monkeypatch.setattr(
        "app.tools.raster_prepare.prepare.clip_raster_to_aoi",
        fake_clip,
    )

    result = prepare_raster_inputs(
        RasterPrepareRequest(
            aoi_query="Test City, Test Country",
            index_name="NDWI",
            start_date="2024-01-01",
            end_date="2024-01-31",
            workspace_dir=tmp_path / "run_1",
        )
    )

    assert captured_required_bands == ["B03", "B08"]
    assert result.required_bands == ["B03", "B08"]
    assert result.band_roles == {"green": "B03", "nir": "B08"}
    assert set(result.band_paths) == {"B03", "B08"}
