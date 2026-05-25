import pytest
from pydantic import ValidationError

from app.tools.workspace import WorkspaceRequest, create_workspace


def test_create_workspace_generates_run_id(tmp_path):
    result = create_workspace(WorkspaceRequest(root_dir=tmp_path))

    workspace_dir = tmp_path / result.run_id
    assert len(result.run_id) == 32
    assert result.workspace_dir == str(workspace_dir)
    assert workspace_dir.exists()


def test_create_workspace_accepts_explicit_run_id(tmp_path):
    result = create_workspace(
        WorkspaceRequest(
            root_dir=tmp_path,
            run_id="manual_run",
        )
    )

    assert result.run_id == "manual_run"
    assert result.workspace_dir == str(tmp_path / "manual_run")
    assert (tmp_path / "manual_run").exists()


def test_create_workspace_rejects_duplicate_explicit_run_id(tmp_path):
    create_workspace(
        WorkspaceRequest(
            root_dir=tmp_path,
            run_id="manual_run",
        )
    )

    with pytest.raises(FileExistsError):
        create_workspace(
            WorkspaceRequest(
                root_dir=tmp_path,
                run_id="manual_run",
            )
        )


def test_workspace_request_rejects_path_like_run_id(tmp_path):
    with pytest.raises(ValidationError):
        WorkspaceRequest(
            root_dir=tmp_path,
            run_id="../outside",
        )
