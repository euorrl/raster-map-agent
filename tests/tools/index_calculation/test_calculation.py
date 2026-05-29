import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from app.tools.index_calculation import (  # noqa: E402
    IndexCalculationError,
    IndexCalculationRequest,
    calculate_raster_index,
)


def test_calculate_raster_index_writes_ndvi(tmp_path):
    clipped_dir = tmp_path / "clipped_raster"
    clipped_dir.mkdir()
    _write_test_raster(
        clipped_dir / "B04_clipped.tif",
        np.array([[1, 2], [-9999, 0]], dtype="float32"),
    )
    _write_test_raster(
        clipped_dir / "B08_clipped.tif",
        np.array([[3, 2], [4, 0]], dtype="float32"),
    )

    result = calculate_raster_index(
        IndexCalculationRequest(
            workspace_dir=tmp_path,
            index_name="NDVI",
            band_roles={"red": "B04", "nir": "B08"},
            index_formula="(nir - red) / (nir + red)",
        )
    )

    assert result.index_tif_path == str(tmp_path / "output" / "ndvi.tif")
    assert not clipped_dir.exists()
    with rasterio.open(result.index_tif_path) as dataset:
        data = dataset.read(1)
        assert dataset.nodata == -9999.0

    np.testing.assert_allclose(data[0, 0], 0.5)
    np.testing.assert_allclose(data[0, 1], 0.0)
    assert data[1, 0] == -9999.0
    assert data[1, 1] == -9999.0


def test_calculate_raster_index_rejects_unknown_formula_role(tmp_path):
    clipped_dir = tmp_path / "clipped_raster"
    clipped_dir.mkdir()
    _write_test_raster(clipped_dir / "B04_clipped.tif", np.ones((2, 2)))

    with pytest.raises(IndexCalculationError, match="unknown band role"):
        calculate_raster_index(
            IndexCalculationRequest(
                workspace_dir=tmp_path,
                index_name="TEST",
                band_roles={"red": "B04"},
                index_formula="nir - red",
            )
        )


def test_calculate_raster_index_resamples_misaligned_bands(tmp_path):
    clipped_dir = tmp_path / "clipped_raster"
    clipped_dir.mkdir()
    _write_test_raster(clipped_dir / "B04_clipped.tif", np.ones((2, 2)))
    _write_test_raster(clipped_dir / "B08_clipped.tif", np.ones((3, 3)))

    result = calculate_raster_index(
        IndexCalculationRequest(
            workspace_dir=tmp_path,
            index_name="NDVI",
            band_roles={"red": "B04", "nir": "B08"},
            index_formula="(nir - red) / (nir + red)",
        )
    )

    assert not clipped_dir.exists()
    with rasterio.open(result.index_tif_path) as dataset:
        data = dataset.read(1)
        assert data.shape == (2, 2)

    np.testing.assert_allclose(data, np.zeros((2, 2)))


def _write_test_raster(path, data):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(data.astype("float32"), 1)
