# flake8: noqa: E402
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tools.render_preview import (
    RenderPreviewRequest,
    render_index_preview,
)  # noqa: E402
from app.utils import configure_logging  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    request = RenderPreviewRequest(
        index_name="NDWI",
        index_tif_path=Path("data/9f8b921411534fbba471b6fcf51f70f0/output/ndwi.tif"),
    )
    result = render_index_preview(request)

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
