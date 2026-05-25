import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """栅格地图 Agent workflow 中流转的共享状态。"""

    user_query: str

    product_type: str | None = None
    workflow_type: str | None = None
    index: str | None = None
    data_source: str | None = None

    aoi_name: str | None = None
    bbox: list[float] | None = None

    required_bands: list[str] = Field(default_factory=list)
    index_formula: str | None = None

    selected_scene: str | None = None
    band_paths: dict[str, str] = Field(default_factory=dict)

    result_tif_path: str | None = None
    preview_path: str | None = None
    metadata_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    final_answer: str | None = None

    status: str = "initialized"
    errors: list[str] = Field(default_factory=list)
    warnings: Annotated[list[str], operator.add] = Field(default_factory=list)
