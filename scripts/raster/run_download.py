# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (
    RasterDownloadRequest,
    RasterSceneCandidateStore,
    RasterScenePlanRequest,
    build_raster_scene_plan,
    download_raster_assets,
)  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    store = RasterSceneCandidateStore()
    workspace_dir = Path("data/speak2")
    boundary_geojson_path = workspace_dir / "aoi" / "Chengdu_Sichuan_China.geojson"
    plan_requests = (
        RasterScenePlanRequest(
            bbox=[102.989623, 30.0916339, 104.8948475, 31.4370968],
            boundary_geojson_path=boundary_geojson_path,
            start_date="2023-12-27",
            end_date="2024-01-09",
            max_cloud_cover=20,
            required_bands=["B04", "B08"],
            data_source="sentinel2",
            limit=100,
        ),
        RasterScenePlanRequest(
            bbox=[102.989623, 30.0916339, 104.8948475, 31.4370968],
            boundary_geojson_path=boundary_geojson_path,
            start_date="2023-12-27",
            end_date="2024-01-09",
            max_cloud_cover=20,
            required_bands=["B04", "B08"],
            data_source="sentinel2",
            limit=100,
        ),
    )

    plan = None
    for plan_request in plan_requests:
        plan = build_raster_scene_plan(plan_request, store=store)

    if plan is None:
        raise RuntimeError("No raster scene plan was built.")

    print("candidate groups:", list(store.groups))
    print("planned scenes:", plan.scene_ids)
    print(plan.diagnostics.model_dump_json(indent=2))

    result = download_raster_assets(
        RasterDownloadRequest(
            plan=plan,
            workspace_dir=workspace_dir,
        )
    )

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
