from dataclasses import dataclass
from typing import Literal, cast

from app.tools.answer.schemas import AnswerMode

WorkflowRoute = Literal["raster_product_generate", "direct_answer"]

RASTER_PRODUCT_GENERATE_ROUTE = "raster_product_generate"
DIRECT_ANSWER_ROUTE = "direct_answer"


@dataclass(frozen=True)
class WorkflowTemplate:
    """受控 workflow 路线模板。

    模板只声明某条 route 的工具序列和默认回答模式，不声明工具参数、
    validator、adjuster 或 retry。工具参数由后续 compiler 根据 state 构造；
    validator、adjuster 和 retry 由 tool_rules 决定。
    """

    route: WorkflowRoute
    description: str
    tool_names: tuple[str, ...]
    answer_mode: AnswerMode


WORKFLOW_TEMPLATES: dict[WorkflowRoute, WorkflowTemplate] = {
    RASTER_PRODUCT_GENERATE_ROUTE: WorkflowTemplate(
        route=RASTER_PRODUCT_GENERATE_ROUTE,
        description="Generate a registered raster product and export metadata.",
        tool_names=(
            "workspace.create_workspace",
            "raster_prepare.prepare_raster_inputs",
            "index_calculation.calculate_raster_index",
            "render_preview.render_index_preview",
            "metadata.export_metadata",
            "answer.generate_final_answer",
        ),
        answer_mode="metadata_summary",
    ),
    DIRECT_ANSWER_ROUTE: WorkflowTemplate(
        route=DIRECT_ANSWER_ROUTE,
        description="Skip raster tools and answer the user directly.",
        tool_names=("answer.generate_final_answer",),
        answer_mode="direct_answer",
    ),
}


def get_workflow_template(route: str) -> WorkflowTemplate:
    """根据 route 读取 workflow template。"""

    try:
        return WORKFLOW_TEMPLATES[cast(WorkflowRoute, route)]
    except KeyError as error:
        raise ValueError(f"Unsupported workflow route: {route}") from error


def get_workflow_template_routes() -> list[str]:
    """返回当前系统支持的 workflow route。"""

    return sorted(WORKFLOW_TEMPLATES)


def get_workflow_route_answer_modes() -> dict[WorkflowRoute, AnswerMode]:
    """返回 route 与默认 answer_mode 的映射。"""

    return {
        route: template.answer_mode
        for route, template in WORKFLOW_TEMPLATES.items()
    }
