import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.metadata.schemas import (
    MetadataExportError,
    MetadataExportRequest,
    MetadataExportResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def export_metadata(request: MetadataExportRequest) -> MetadataExportResult:
    """把 workflow metadata 导出为 JSON 文件。"""

    logger.info("Exporting metadata path=%s", request.output_path)
    payload = _build_metadata_payload(request.metadata)

    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.output_path.write_text(
            json.dumps(
                payload,
                default=_json_default,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError) as error:
        raise MetadataExportError(
            f"Failed to export metadata: {request.output_path}"
        ) from error

    logger.info("Exported metadata path=%s", request.output_path)
    return MetadataExportResult(metadata_path=str(request.output_path))


def _build_metadata_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if isinstance(value, set):
        return sorted(value)

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
