# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (  # noqa: E402
    RasterMosaicRequest,
    mosaic_rasters_by_band,
)
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    workspace_dir = Path("data/speak2")
    result = mosaic_rasters_by_band(
        RasterMosaicRequest(
            input_dir=workspace_dir / "raster",
            output_dir=workspace_dir / "mosaic_raster",
        )
    )

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
