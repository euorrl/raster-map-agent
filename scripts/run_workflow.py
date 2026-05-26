from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import configure_logging  # noqa: E402
from app.workflows.workflow import run_workflow  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    user_query = "Generate an NDVI vegetation map for Chengdu."
    state = run_workflow(user_query)

    print("status:", state.status)
    print("final_answer:", state.final_answer)
    print("workspace_dir:", state.workspace.get("workspace_dir"))
    print(
        "index_tif_path:",
        state.tool_results.get("index_calculation", {}).get("index_tif_path"),
    )
    print(
        "preview_path:",
        state.tool_results.get("render_preview", {}).get("preview_path"),
    )
    print(
        "metadata_path:",
        state.tool_results.get("metadata_export", {}).get("metadata_path"),
    )
    if state.errors:
        print("errors:", state.errors)
    if state.warnings:
        print("warnings:", state.warnings)


if __name__ == "__main__":
    main()
