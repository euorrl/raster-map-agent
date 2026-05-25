from uuid import uuid4

from app.tools.workspace.schemas import WorkspaceRequest, WorkspaceResult
from app.utils.logging import get_logger

logger = get_logger(__name__)


def create_workspace(request: WorkspaceRequest | None = None) -> WorkspaceResult:
    """创建一次任务专用的 workspace 目录。"""

    request = request or WorkspaceRequest()
    root_dir = request.root_dir
    root_dir.mkdir(parents=True, exist_ok=True)

    if request.run_id is not None:
        workspace_dir = root_dir / request.run_id
        workspace_dir.mkdir(parents=True, exist_ok=False)
        logger.info(
            "Created workspace run_id=%s path=%s", request.run_id, workspace_dir
        )
        return WorkspaceResult(
            run_id=request.run_id,
            workspace_dir=str(workspace_dir),
        )

    while True:
        run_id = uuid4().hex
        workspace_dir = root_dir / run_id
        try:
            workspace_dir.mkdir()
        except FileExistsError:
            continue

        logger.info("Created workspace run_id=%s path=%s", run_id, workspace_dir)
        return WorkspaceResult(
            run_id=run_id,
            workspace_dir=str(workspace_dir),
        )
