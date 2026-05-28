from dataclasses import dataclass
from typing import Literal, cast

from app.tools.answer.schemas import AnswerMode

WorkflowRoute = Literal["raster_product_generate", "direct_answer"]

RASTER_PRODUCT_GENERATE_ROUTE = "raster_product_generate"
DIRECT_ANSWER_ROUTE = "direct_answer"


@dataclass(frozen=True)
class WorkflowTemplate:
    """Controlled workflow route template.

    The template only declares the tool sequence and default answer mode for a
    route. Tool parameters are compiled later from state. Validator, adjuster,
    and retry behavior are controlled by workflow tool rules.
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
    """Return the workflow template registered for route."""

    try:
        return WORKFLOW_TEMPLATES[cast(WorkflowRoute, route)]
    except KeyError as error:
        raise ValueError(f"Unsupported workflow route: {route}") from error


def get_workflow_template_routes() -> list[str]:
    """Return supported workflow route names."""

    return sorted(WORKFLOW_TEMPLATES)


def get_workflow_route_answer_modes() -> dict[WorkflowRoute, AnswerMode]:
    """Return the default answer mode for each workflow route."""

    return {
        route: template.answer_mode for route, template in WORKFLOW_TEMPLATES.items()
    }
