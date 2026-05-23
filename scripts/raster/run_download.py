# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (
    RasterDownloadRequest,
    download_raster_bands,
)  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = RasterDownloadRequest(
        bbox=[9.0408867, 45.3867381, 9.2781103, 45.5358482],
        start_date="2023-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
        workspace_dir=Path("data/speak2"),
    )

    result = download_raster_bands(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
