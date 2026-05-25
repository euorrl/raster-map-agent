from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class RenderPreviewError(RuntimeError):
    """渲染预览图失败时抛出的错误。"""


class RenderPreviewRequest(BaseModel):
    """渲染预览图请求。

    Attributes:
        index_name: 指数名称，例如 ``NDVI``。
        index_tif_path: 指数 GeoTIFF 路径。
        output_filename: 可选输出文件名，不传则自动生成。
        max_size: 预览图最长边像素数。
        include_colorbar: 是否在 PNG 右下角绘制简化色带图例。
    """

    index_name: str
    index_tif_path: Path
    output_filename: str | None = None
    max_size: int = Field(default=2048, ge=256, le=8192)
    include_colorbar: bool = True

    @property
    def output_path(self) -> Path:
        """预览 PNG 输出路径。"""

        filename = self.output_filename or f"{self.index_name.lower()}_preview.png"
        return self.index_tif_path.parent / filename

    @field_validator("index_name")
    @classmethod
    def normalize_index_name(cls, index_name: str) -> str:
        """把指数名称统一转为大写。"""

        return index_name.upper()


class RenderPreviewResult(BaseModel):
    """渲染预览图结果。"""

    preview_path: str
