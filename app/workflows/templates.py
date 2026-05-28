from dataclasses import dataclass
from typing import Literal, cast

from app.tools.answer.schemas import AnswerMode

WorkflowRoute = Literal["raster_product_generate", "direct_answer"]

RASTER_PRODUCT_GENERATE_ROUTE = "raster_product_generate"
DIRECT_ANSWER_ROUTE = "direct_answer"


@dataclass(frozen=True)
class WorkflowTemplate:
    """受控 workflow 路由模板。

    模板只声明某条路由的工具顺序和默认回答模式。工具参数后续由 compiler
    根据 state 编译生成；validator、adjuster 和 retry 行为由 tool rules 控制。
    """

    route: WorkflowRoute
    description: str
    tool_names: tuple[str, ...]
    answer_mode: AnswerMode


WORKFLOW_TEMPLATES: dict[WorkflowRoute, WorkflowTemplate] = {
    RASTER_PRODUCT_GENERATE_ROUTE: WorkflowTemplate(
        route=RASTER_PRODUCT_GENERATE_ROUTE,
        description="生成已注册的栅格产品并导出元数据。",
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
        description="跳过栅格工具，直接回答用户问题。",
        tool_names=("answer.generate_final_answer",),
        answer_mode="direct_answer",
    ),
}


def get_workflow_template(route: str) -> WorkflowTemplate:
    """返回指定 route 注册的 workflow 模板。"""

    try:
        return WORKFLOW_TEMPLATES[cast(WorkflowRoute, route)]
    except KeyError as error:
        raise ValueError(f"Unsupported workflow route: {route}") from error


def get_workflow_template_routes() -> list[str]:
    """返回当前支持的 workflow route 名称。"""

    return sorted(WORKFLOW_TEMPLATES)


def get_workflow_route_answer_modes() -> dict[WorkflowRoute, AnswerMode]:
    """返回每条 workflow route 的默认回答模式。"""

    return {
        route: template.answer_mode for route, template in WORKFLOW_TEMPLATES.items()
    }
