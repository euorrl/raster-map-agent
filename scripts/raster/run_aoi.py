# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.raster_prepare import (
    AOIRequest,
    resolve_administrative_aoi,
)  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = AOIRequest(
        query="Changsha, Hunan, China",
        workspace_dir=Path("data/speak2"),
    )

    result = resolve_administrative_aoi(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
