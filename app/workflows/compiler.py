from typing import Any

from pydantic import BaseModel, Field

from app.schemas import AgentState
from app.workflows.templates import (
    DIRECT_ANSWER_ROUTE,
    RASTER_PRODUCT_GENERATE_ROUTE,
    WorkflowTemplate,
    get_workflow_template,
)


class ToolCall(BaseModel):
    """编译后的工具调用，包含已确定参数和运行时 state 引用。"""

    id: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    result_key: str | None = None


def compile_tool_calls(state: AgentState) -> list[dict[str, Any]]:
    """把 state.plan 和 registry 上下文编译为有序工具调用。"""

    route = state.plan.get("route", RASTER_PRODUCT_GENERATE_ROUTE)
    template = get_workflow_template(route)

    if route == DIRECT_ANSWER_ROUTE:
        return _dump_tool_calls(_compile_direct_answer_calls(state, template))

    if route == RASTER_PRODUCT_GENERATE_ROUTE:
        return _dump_tool_calls(_compile_raster_product_calls(state, template))

    raise ValueError(f"Unsupported workflow route: {route}")


def build_tool_calls_update(state: AgentState) -> dict[str, Any]:
    """构造写入编译后 tool_calls 的 state 更新。"""

    route = state.plan.get("route", RASTER_PRODUCT_GENERATE_ROUTE)
    tool_calls = compile_tool_calls(state)
    return {
        "tool_calls": tool_calls,
        "runtime": {
            "compiler": {
                "route": route,
                "tool_call_count": len(tool_calls),
            }
        },
    }


def _compile_direct_answer_calls(
    state: AgentState,
    template: WorkflowTemplate,
) -> list[ToolCall]:
    return [
        ToolCall(
            id="answer",
            tool_name=template.tool_names[0],
            params={
                "answer_mode": state.plan.get("answer_mode", template.answer_mode),
                "question": "$state.user_query",
            },
            result_key="final_answer",
        )
    ]


def _compile_raster_product_calls(
    state: AgentState,
    template: WorkflowTemplate,
) -> list[ToolCall]:
    raster_product = _get_registry_raster_product(state)
    _require_plan_fields(
        state.plan,
        [
            "aoi_query",
            "index_name",
            "start_date",
            "end_date",
        ],
    )
    _require_fields(
        raster_product,
        [
            "data_source",
            "band_roles",
            "index_formula",
        ],
        "runtime.registry.raster_product",
    )

    return [
        ToolCall(
            id="workspace",
            tool_name=template.tool_names[0],
            result_key="workspace",
        ),
        ToolCall(
            id="raster_prepare",
            tool_name=template.tool_names[1],
            params={
                "aoi_query": state.plan["aoi_query"],
                "index_name": state.plan["index_name"],
                "data_source": raster_product["data_source"],
                "start_date": state.plan["start_date"],
                "end_date": state.plan["end_date"],
                "max_cloud_cover": state.plan.get("max_cloud_cover", 20),
                "workspace_dir": "$state.workspace.workspace_dir",
            },
            depends_on=["workspace"],
            result_key="raster_prepare",
        ),
        ToolCall(
            id="index_calculation",
            tool_name=template.tool_names[2],
            params={
                "workspace_dir": "$state.workspace.workspace_dir",
                "index_name": state.plan["index_name"],
                "band_roles": raster_product["band_roles"],
                "index_formula": raster_product["index_formula"],
            },
            depends_on=["raster_prepare"],
            result_key="index_calculation",
        ),
        ToolCall(
            id="render_preview",
            tool_name=template.tool_names[3],
            params={
                "index_name": state.plan["index_name"],
                "index_tif_path": (
                    "$state.tool_results.index_calculation.index_tif_path"
                ),
            },
            depends_on=["index_calculation"],
            result_key="render_preview",
        ),
        ToolCall(
            id="metadata_export",
            tool_name=template.tool_names[4],
            params={
                "workspace_dir": "$state.workspace.workspace_dir",
                "workflow_state": "$state",
            },
            depends_on=["raster_prepare", "index_calculation", "render_preview"],
            result_key="metadata_export",
        ),
        ToolCall(
            id="answer",
            tool_name=template.tool_names[5],
            params={
                "answer_mode": state.plan.get("answer_mode", template.answer_mode),
                "user_query": "$state.user_query",
                "metadata": "$state.tool_results.metadata_export.product_info",
            },
            depends_on=["metadata_export"],
            result_key="final_answer",
        ),
    ]


def _dump_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [tool_call.model_dump(mode="json") for tool_call in tool_calls]


def _get_registry_raster_product(state: AgentState) -> dict[str, Any]:
    registry = state.runtime.get("registry", {})
    if not isinstance(registry, dict):
        return {}

    raster_product = registry.get("raster_product", {})
    if isinstance(raster_product, dict):
        return raster_product

    return {}


def _require_plan_fields(plan: dict[str, Any], fields: list[str]) -> None:
    _require_fields(plan, fields, "plan")


def _require_fields(
    values: dict[str, Any],
    fields: list[str],
    context: str,
) -> None:
    missing_fields = [field for field in fields if values.get(field) in (None, "")]
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise ValueError(f"Missing {context} fields: {joined_fields}")
