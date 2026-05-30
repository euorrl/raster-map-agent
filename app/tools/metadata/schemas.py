from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

METADATA_OUTPUT_DIRNAME = "output"


class MetadataExportError(RuntimeError):
    """Metadata export 失败时抛出的错误。"""


class MetadataExportRequest(BaseModel):
    """Metadata 导出请求。

    workflow_state 是调用节点传入的 AgentState 快照。metadata tool 会优先从
    真实 tool_results 抽取产品输出信息，并从实际 GeoTIFF 读取空间信息，而不是
    原样导出完整 state。
    """

    workspace_dir: Path
    workflow_state: dict[str, Any] = Field(default_factory=dict)
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
    product_info: dict[str, Any] = Field(default_factory=dict)
