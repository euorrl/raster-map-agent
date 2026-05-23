from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster import RasterClipRequest, clip_raster_to_aoi  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = RasterClipRequest(
        raster_path=Path("data/speak1/raster/S2A_32TNR_20240828_0_L2A_B04.tif"),
        boundary_geojson_path=Path("data/speak1/aoi/Milano_Lombardy_Italy.geojson"),
        output_path=Path("data/speak1/clipped_raster/clipped_B04.tif"),
    )

    result = clip_raster_to_aoi(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
