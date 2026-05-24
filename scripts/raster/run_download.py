# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (
    RasterDownloadRequest,
    RasterScenePlanRequest,
    build_raster_scene_plan,
    download_raster_assets,
)  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    plan_request = RasterScenePlanRequest(
        bbox=[102.989623,
            30.0916339,
            104.8948475,
            31.4370968
        ],
        start_date="2023-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
    )

    plan = build_raster_scene_plan(plan_request)
    result = download_raster_assets(
        RasterDownloadRequest(
            plan=plan,
            workspace_dir=Path("data/speak2"),
        )
    )

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
