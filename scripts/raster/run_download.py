from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster import RasterDownloadRequest, download_raster_bands  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = RasterDownloadRequest(
        bbox=[
        8.706096074466394,
        45.16147199717692,
        9.551562493000636,
        45.64266804682561
    ],
        start_date="2024-06-01",
        end_date="2024-08-31",
        max_cloud_cover=20,
        required_bands=["B04", "B08"],
        output_dir=Path("data/speak1/raster"),
    )

    result = download_raster_bands(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
