from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from app.tools.raster_prepare.schemas import CLIPPED_RASTER_DIRNAME, OUTPUT_DIRNAME


class IndexCalculationError(RuntimeError):
    """指数计算失败时抛出的错误。"""


class IndexCalculationRequest(BaseModel):
    """指数计算请求。

    Attributes:
        workspace_dir: 当前任务的 UUID workspace 路径。
        index_name: 指数名称，例如 ``NDVI``。
        band_roles: 指数公式中的角色到真实波段名的映射。
        index_formula: 人类可读的指数公式，用于 metadata。
        output_filename: 可选输出文件名。
    """

    workspace_dir: Path
    index_name: str
    band_roles: dict[str, str] = Field(min_length=1)
    index_formula: str
    output_filename: str | None = None

    @property
    def clipped_raster_dir(self) -> Path:
        """prepare 阶段输出 clipped bands 的固定目录。"""

        return self.workspace_dir / CLIPPED_RASTER_DIRNAME

    @property
    def output_dir(self) -> Path:
        """指数 GeoTIFF 输出目录。"""

        return self.workspace_dir / OUTPUT_DIRNAME

    @property
    def output_path(self) -> Path:
        """指数 GeoTIFF 输出路径。"""

        filename = self.output_filename or "result.tif"
        return self.output_dir / filename

    @property
    def band_paths(self) -> dict[str, Path]:
        """根据 band_roles 从 clipped_raster 目录推导输入 band 路径。"""

        return {
            band: self.clipped_raster_dir / f"{band}_clipped.tif"
            for band in self.band_roles.values()
        }

    @field_validator("index_name")
    @classmethod
    def normalize_index_name(cls, index_name: str) -> str:
        """把指数名称统一转为大写。"""

        return index_name.upper()

    @model_validator(mode="after")
    def normalize_band_roles(self):
        self.band_roles = {role: band.upper() for role, band in self.band_roles.items()}

        return self


class IndexCalculationResult(BaseModel):
    """指数计算结果。"""

    index_tif_path: str
