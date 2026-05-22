from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster import RasterDownloadRequest, download_raster_bands  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = RasterDownloadRequest(
        bbox=[9, 25.35, 29.32, 45.56],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
        output_dir=Path("data/speak3"),
    )

    result = download_raster_bands(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
