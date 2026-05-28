import json

import pytest
from pydantic import ValidationError

from app.tools.metadata import MetadataExportRequest, export_metadata


def test_export_metadata_writes_json_to_workspace_output(tmp_path):
    request = MetadataExportRequest(
        workspace_dir=tmp_path,
        metadata={
            "plan": {
                "index_name": "NDVI",
                "aoi_query": "Chengdu, Sichuan, China",
            },
            "render_preview": {
                "preview_path": "data/run/output/ndvi_preview.png",
            },
        },
    )

    result = export_metadata(request)
    metadata_path = tmp_path / "output" / "metadata.json"

    assert result.metadata_path == str(metadata_path)
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["exported_at"]
    assert payload["metadata"]["plan"]["index_name"] == "NDVI"
    assert payload["metadata"]["render_preview"]["preview_path"].endswith(
        "ndvi_preview.png"
    )


def test_export_metadata_accepts_custom_output_filename(tmp_path):
    result = export_metadata(
        MetadataExportRequest(
            workspace_dir=tmp_path,
            metadata={"status": "completed"},
            output_filename="run_metadata.json",
        )
    )

    assert result.metadata_path == str(tmp_path / "output" / "run_metadata.json")


def test_export_metadata_serializes_path_values(tmp_path):
    export_metadata(
        MetadataExportRequest(
            workspace_dir=tmp_path,
            metadata={"workspace_dir": tmp_path},
        )
    )

    payload = json.loads(
        (tmp_path / "output" / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["metadata"]["workspace_dir"] == str(tmp_path)


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
