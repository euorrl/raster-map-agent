from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import configure_logging  # noqa: E402
from app.workflows.workflow import run_workflow  # noqa: E402


def main() -> None:
    configure_logging("INFO")

    user_query = "想看看成都最近的植被分布如何"
    state = run_workflow(user_query)

    print("\n" + "-" * 30 + "\n")
    print("final_answer:", state.final_answer)


if __name__ == "__main__":
    main()
