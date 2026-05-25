from pathlib import Path

from app.tools.render_preview import RenderPreviewRequest


def test_render_preview_request_uses_index_tif_parent_as_output_dir(tmp_path):
    request = RenderPreviewRequest(
        index_name="ndvi",
        index_tif_path=tmp_path / "output" / "ndvi.tif",
    )

    assert request.index_name == "NDVI"
    assert request.output_path == tmp_path / "output" / "ndvi_preview.png"


def test_render_preview_request_allows_custom_output_filename(tmp_path):
    request = RenderPreviewRequest(
        index_name="NDWI",
        index_tif_path=tmp_path / "output" / "ndwi.tif",
        output_filename="water_preview.png",
    )

    assert request.output_path == Path(tmp_path / "output" / "water_preview.png")
