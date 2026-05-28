from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.schemas import AgentState
from app.schemas.state import merge_dicts
from app.tools.answer import (
    FinalAnswerRequest,
    generate_final_answer,
)
from app.tools.index_calculation import (
    IndexCalculationRequest,
    calculate_raster_index,
)
from app.tools.metadata import MetadataExportRequest, export_metadata
from app.tools.raster_prepare import RasterPrepareRequest, prepare_raster_inputs
from app.tools.render_preview import RenderPreviewRequest, render_index_preview
from app.tools.workspace import WorkspaceRequest, create_workspace
from app.workflows.compiler import ToolCall

ToolFn = Callable[[Any], Any]


class ToolExecutionError(RuntimeError):
    """工具执行失败时抛出的 workflow 层错误。"""


@dataclass(frozen=True)
class ToolSpec:
    """executor 可调用工具的运行规范。"""

    tool_name: str
    request_model: type[BaseModel]
    tool_fn: ToolFn
    result_target: str = "tool_results"


TOOL_SPECS: dict[str, ToolSpec] = {
    "workspace.create_workspace": ToolSpec(
        tool_name="workspace.create_workspace",
        request_model=WorkspaceRequest,
        tool_fn=create_workspace,
        result_target="workspace",
    ),
    "raster_prepare.prepare_raster_inputs": ToolSpec(
        tool_name="raster_prepare.prepare_raster_inputs",
        request_model=RasterPrepareRequest,
        tool_fn=prepare_raster_inputs,
    ),
    "index_calculation.calculate_raster_index": ToolSpec(
        tool_name="index_calculation.calculate_raster_index",
        request_model=IndexCalculationRequest,
        tool_fn=calculate_raster_index,
    ),
    "render_preview.render_index_preview": ToolSpec(
        tool_name="render_preview.render_index_preview",
        request_model=RenderPreviewRequest,
        tool_fn=render_index_preview,
    ),
    "metadata.export_metadata": ToolSpec(
        tool_name="metadata.export_metadata",
        request_model=MetadataExportRequest,
        tool_fn=export_metadata,
    ),
    "answer.generate_final_answer": ToolSpec(
        tool_name="answer.generate_final_answer",
        request_model=FinalAnswerRequest,
        tool_fn=generate_final_answer,
        result_target="final_answer",
    ),
}


def execute_current_tool_call(
    state: AgentState,
    tool_specs: dict[str, ToolSpec] | None = None,
) -> AgentState:
    """执行当前 state.runtime.current_tool_index 指向的单个 tool_call。"""

    specs = tool_specs or TOOL_SPECS
    current_state = AgentState.model_validate(state.model_dump(mode="json"))
    index = int(current_state.runtime.get("current_tool_index", 0))

    if index >= len(current_state.tool_calls):
        return _apply_update(
            current_state,
            {
                "status": "no_more_tools",
            },
        )

    raw_tool_call = current_state.tool_calls[index]
    tool_call = ToolCall.model_validate(raw_tool_call)
    executed_call_ids = [
        ToolCall.model_validate(item).id for item in current_state.tool_calls[:index]
    ]
    _ensure_dependencies_are_done(tool_call, executed_call_ids)

    spec = _get_tool_spec(specs, tool_call.tool_name)
    params = _resolve_state_references(tool_call.params, current_state)
    request = spec.request_model.model_validate(params)
    result = spec.tool_fn(request)
    result_data = _dump_result(result)

    update = _build_tool_result_update(tool_call, spec, result_data)
    update = merge_dicts(
        update,
        {
            "runtime": {
                "last_tool_index": index,
                "last_tool_call_id": tool_call.id,
                "last_tool_name": tool_call.tool_name,
                "current_tool_index": index + 1,
            },
        },
    )
    if "status" not in update:
        update["status"] = "tool_executed"

    return _apply_update(current_state, update)


def execute_tool_calls(
    state: AgentState,
    tool_specs: dict[str, ToolSpec] | None = None,
) -> AgentState:
    """按顺序执行 state.tool_calls，并返回执行后的 state。"""

    specs = tool_specs or TOOL_SPECS
    current_state = AgentState.model_validate(state.model_dump(mode="json"))
    executed_call_ids: list[str] = []

    while int(current_state.runtime.get("current_tool_index", 0)) < len(
        current_state.tool_calls
    ):
        current_state = execute_current_tool_call(current_state, specs)
        executed_call_ids.append(current_state.runtime["last_tool_call_id"])

    current_state = _apply_update(
        current_state,
        {
            "runtime": {
                "executor": {
                    "executed_tool_calls": executed_call_ids,
                }
            }
        },
    )
    return current_state


def _ensure_dependencies_are_done(
    tool_call: ToolCall,
    executed_call_ids: list[str],
) -> None:
    missing_dependencies = [
        dependency
        for dependency in tool_call.depends_on
        if dependency not in executed_call_ids
    ]
    if missing_dependencies:
        joined_dependencies = ", ".join(missing_dependencies)
        raise ToolExecutionError(
            f"Tool call {tool_call.id} has unmet dependencies: "
            f"{joined_dependencies}"
        )


def _get_tool_spec(
    specs: dict[str, ToolSpec],
    tool_name: str,
) -> ToolSpec:
    try:
        return specs[tool_name]
    except KeyError as error:
        raise ToolExecutionError(f"Unsupported tool: {tool_name}") from error


def _resolve_state_references(value: Any, state: AgentState) -> Any:
    if isinstance(value, str):
        return _resolve_state_reference(value, state)

    if isinstance(value, dict):
        return {
            key: _resolve_state_references(item, state) for key, item in value.items()
        }

    if isinstance(value, list):
        return [_resolve_state_references(item, state) for item in value]

    return value


def _resolve_state_reference(value: str, state: AgentState) -> Any:
    if value == "$state":
        return state.model_dump(mode="json")

    if not value.startswith("$state."):
        return value

    data: Any = state.model_dump(mode="json")
    path = value.removeprefix("$state.").split(".")
    for part in path:
        if not isinstance(data, dict) or part not in data:
            raise ToolExecutionError(f"State reference cannot be resolved: {value}")
        data = data[part]

    return data


def _build_tool_result_update(
    tool_call: ToolCall,
    spec: ToolSpec,
    result_data: dict[str, Any],
) -> dict[str, Any]:
    if spec.result_target == "workspace":
        return {"workspace": result_data}

    if spec.result_target == "final_answer":
        return {
            "final_answer": result_data["final_answer"],
            "status": "completed",
        }

    result_key = tool_call.result_key or tool_call.id
    return {"tool_results": {result_key: result_data}}


def _dump_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")

    if isinstance(result, dict):
        return result

    raise ToolExecutionError(
        f"Tool result must be a pydantic model or dict: {type(result).__name__}"
    )


def _apply_update(state: AgentState, update: dict[str, Any]) -> AgentState:
    data = state.model_dump(mode="json")
    for key, value in update.items():
        if key in {
            "plan",
            "workspace",
            "tool_results",
            "runtime",
        }:
            data[key] = merge_dicts(data.get(key, {}), value)
        elif key in {"errors", "warnings"}:
            data[key] = data.get(key, []) + value
        else:
            data[key] = value

    return AgentState.model_validate(data)
