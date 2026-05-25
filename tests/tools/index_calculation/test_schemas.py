from pathlib import Path

from app.tools.index_calculation import IndexCalculationRequest


def test_index_calculation_request_uses_workspace_layout(tmp_path):
    request = IndexCalculationRequest(
        workspace_dir=tmp_path,
        index_name="ndvi",
        band_roles={"red": "B04", "nir": "B08"},
        index_formula="(nir - red) / (nir + red)",
    )

    assert request.index_name == "NDVI"
    assert request.clipped_raster_dir == tmp_path / "clipped_raster"
    assert request.output_dir == tmp_path / "output"
    assert request.output_path == tmp_path / "output" / "ndvi.tif"
    assert request.band_paths == {
        "B04": tmp_path / "clipped_raster" / "B04_clipped.tif",
        "B08": tmp_path / "clipped_raster" / "B08_clipped.tif",
    }


def test_index_calculation_request_normalizes_band_roles(tmp_path):
    request = IndexCalculationRequest(
        workspace_dir=tmp_path,
        index_name="NDWI",
        band_roles={"green": "b03", "nir": "b08"},
        index_formula="(green - nir) / (green + nir)",
    )

    assert request.band_roles == {"green": "B03", "nir": "B08"}
    assert request.band_paths == {
        "B03": tmp_path / "clipped_raster" / "B03_clipped.tif",
        "B08": tmp_path / "clipped_raster" / "B08_clipped.tif",
    }


def test_index_calculation_request_allows_custom_output_filename(tmp_path):
    request = IndexCalculationRequest(
        workspace_dir=tmp_path,
        index_name="NDWI",
        band_roles={"green": "B03", "nir": "B08"},
        index_formula="(green - nir) / (green + nir)",
        output_filename="water_index.tif",
    )

    assert request.output_path == Path(tmp_path / "output" / "water_index.tif")
