from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

METADATA_OUTPUT_DIRNAME = "output"


class MetadataExportError(RuntimeError):
    """Metadata export 失败时抛出的错误。"""


class MetadataExportRequest(BaseModel):
    """Metadata 导出请求。"""

    workspace_dir: Path
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_filename: str = Field(default="metadata.json", min_length=1)

    @property
    def output_dir(self) -> Path:
        """Metadata 固定输出目录。"""

        return self.workspace_dir / METADATA_OUTPUT_DIRNAME

    @property
    def output_path(self) -> Path:
        """Metadata JSON 输出路径。"""

        return self.output_dir / self.output_filename

    @field_validator("output_filename")
    @classmethod
    def reject_path_like_filename(cls, output_filename: str) -> str:
        """只允许普通文件名，避免写出 workspace output 目录。"""

        path = Path(output_filename)
        if path.name != output_filename or path.is_absolute():
            raise ValueError("output_filename must be a plain filename.")

        if path.suffix.lower() != ".json":
            raise ValueError("output_filename must use .json extension.")

        return output_filename


class MetadataExportResult(BaseModel):
    """Metadata 导出结果。"""

    metadata_path: str
