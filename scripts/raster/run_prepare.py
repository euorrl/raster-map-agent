# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (  # noqa: E402
    RasterPrepareRequest,
    prepare_raster_inputs,
)
from app.tools.workspace import WorkspaceRequest, create_workspace  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")
    workspace = create_workspace(WorkspaceRequest(root_dir=Path("data")))

    result = prepare_raster_inputs(
        RasterPrepareRequest(
            aoi_query="Beijing, China",
            index_name="NDWI",
            start_date="2023-12-27",
            end_date="2024-01-09",
            workspace_dir=Path(workspace.workspace_dir),
        )
    )

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
