# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.registry import resolve_raster_product_config  # noqa: E402
from app.tools.index_calculation import (  # noqa: E402
    IndexCalculationRequest,
    calculate_raster_index,
)
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    workspace_dir = Path("data/9f8b921411534fbba471b6fcf51f70f0")
    product_config = resolve_raster_product_config("NDWI", "sentinel2")

    result = calculate_raster_index(
        IndexCalculationRequest(
            workspace_dir=workspace_dir,
            index_name=product_config.index_name,
            band_roles=product_config.band_roles,
            index_formula=product_config.index_formula,
        )
    )

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
