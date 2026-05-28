import json

import pytest
from pydantic import ValidationError

from app.tools.metadata import (
    MetadataExportRequest,
    build_product_info,
    export_metadata,
)


def test_export_metadata_writes_compact_product_info(tmp_path):
    workflow_state = _build_workflow_state(tmp_path)
    request = MetadataExportRequest(
        workspace_dir=tmp_path,
        workflow_state=workflow_state,
    )

    result = export_metadata(request)
    metadata_path = tmp_path / "output" / "metadata.json"

    assert result.metadata_path == str(metadata_path)
    assert metadata_path.exists()
    assert result.product_info["product"]["name"] == "NDVI"
    assert result.product_info["source"]["provider"] == "earth_search"

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "schema_version" not in payload
    assert "exported_at" not in payload
    assert "product_info" not in payload
    assert "metadata" not in payload
    product_info = payload
    assert product_info["product"] == {
        "type": "index",
        "name": "NDVI",
        "family": "raster",
        "method": {
            "name": "index_formula",
            "formula": "(nir - red) / (nir + red)",
        },
    }
    assert product_info["area"] == {"aoi_query": "Chengdu, Sichuan, China"}
    assert product_info["time_range"] == {
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
    }
    assert product_info["source"]["data_source"] == "sentinel2"
    assert product_info["source"]["provider"] == "earth_search"
    assert "satellite" not in product_info["source"]
    assert "collection" not in product_info["source"]
    assert product_info["quality"]["raster_prepare_validation_status"] == "passed"
    assert "boundary_geojson_path" not in product_info["area"]
    assert "outputs" not in product_info


def test_build_product_info_drops_empty_sections(tmp_path):
    product_info = build_product_info(
        {
            "plan": {
                "index_name": "NDWI",
            },
            "tool_results": {},
            "runtime": {},
            "warnings": [],
        }
    )

    assert product_info == {
        "product": {
            "type": "index",
            "name": "NDWI",
            "family": "raster",
        }
    }


def test_build_product_info_handles_non_index_product_without_formula(tmp_path):
    product_info = build_product_info(
        {
            "plan": {
                "product_type": "landtype",
                "product_name": "landtype",
                "aoi_query": "Chengdu, Sichuan, China",
            },
            "runtime": {
                "registry": {
                    "raster_product": {
                        "product_type": "landtype",
                        "product_name": "landtype",
                        "data_source": "landcover_catalog",
                    }
                }
            },
            "tool_results": {},
        }
    )

    assert product_info["product"] == {
        "type": "landtype",
        "name": "landtype",
        "family": "raster",
    }


def test_build_product_info_reads_spatial_profile_from_product_tif(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    numpy = pytest.importorskip("numpy")
    from rasterio.transform import from_origin

    product_tif_path = tmp_path / "output" / "ndvi.tif"
    product_tif_path.parent.mkdir()
    with rasterio.open(
        product_tif_path,
        "w",
        driver="GTiff",
        height=2,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(100, 200, 10, 10),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(numpy.ones((2, 3), dtype="float32"), 1)

    workflow_state = _build_workflow_state(tmp_path)
    workflow_state["tool_results"]["index_calculation"][
        "index_tif_path"
    ] = str(product_tif_path)

    product_info = build_product_info(workflow_state)

    assert product_info["spatial"]["crs"] == "EPSG:3857"
    assert product_info["spatial"]["resolution"] == {
        "x": 10.0,
        "y": 10.0,
        "unit": "metre",
    }
    assert product_info["spatial"]["resolution_meters"] == 10.0
    assert product_info["spatial"]["width"] == 3
    assert product_info["spatial"]["height"] == 2
    assert product_info["spatial"]["bounds"] == {
        "left": 100.0,
        "bottom": 180.0,
        "right": 130.0,
        "top": 200.0,
    }
    assert "source_raster_path" not in product_info["spatial"]


def test_export_metadata_accepts_custom_output_filename(tmp_path):
    result = export_metadata(
        MetadataExportRequest(
            workspace_dir=tmp_path,
            workflow_state=_build_workflow_state(tmp_path),
            output_filename="run_metadata.json",
        )
    )

    assert result.metadata_path == str(tmp_path / "output" / "run_metadata.json")


def test_metadata_export_request_rejects_path_like_output_filename(tmp_path):
    with pytest.raises(ValidationError):
        MetadataExportRequest(
            workspace_dir=tmp_path,
            output_filename="../metadata.json",
        )


def test_metadata_export_request_requires_json_output_filename(tmp_path):
    with pytest.raises(ValidationError):
        MetadataExportRequest(
            workspace_dir=tmp_path,
            output_filename="metadata.txt",
        )


def _build_workflow_state(tmp_path):
    return {
        "plan": {
            "route": "raster_product_generate",
            "answer_mode": "metadata_summary",
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "NDVI",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 20,
        },
        "runtime": {
            "registry": {
                "raster_product": {
                    "index_name": "NDVI",
                    "data_source": "sentinel2",
                    "required_bands": ["B04", "B08"],
                    "band_roles": {"red": "B04", "nir": "B08"},
                    "index_formula": "(nir - red) / (nir + red)",
                    "provider": "earth_search",
                    "collection": "sentinel-2-l2a",
                }
            },
            "validators": {
                "raster_prepare": {
                    "status": "passed",
                }
            },
        },
        "tool_results": {
            "raster_prepare": {
                "boundary_geojson_path": str(tmp_path / "aoi" / "chengdu.geojson"),
                "index_name": "NDVI",
                "data_source": "sentinel2",
                "provider": "earth_search",
                "collection": "sentinel-2-l2a",
                "index_formula": "(nir - red) / (nir + red)",
                "diagnostics": {
                    "coverage_status": "covered",
                    "coverage_ratio": 1,
                    "min_coverage_ratio": 0.7,
                    "selected_scene_count": 1,
                },
            },
            "index_calculation": {
                "index_tif_path": str(tmp_path / "output" / "ndvi.tif"),
            },
            "render_preview": {
                "preview_path": str(tmp_path / "output" / "ndvi_preview.png"),
            },
        },
        "warnings": [],
    }
