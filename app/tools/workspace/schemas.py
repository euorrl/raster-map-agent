from pathlib import Path

from pydantic import BaseModel, Field


class WorkspaceRequest(BaseModel):
    """Workspace 创建请求。"""

    root_dir: Path = Path("data")
    run_id: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class WorkspaceResult(BaseModel):
    """Workspace 创建结果。"""

    run_id: str
    workspace_dir: str
