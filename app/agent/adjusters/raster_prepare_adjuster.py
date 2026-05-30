import json
from datetime import datetime
from typing import Any, Callable, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.schemas import AgentState
from app.utils import get_zhipuai_settings

RasterPrepareAdjustmentStatus = Literal["adjusted", "skipped", "failed"]
LLMClient = Callable[[list[dict[str, str]]], str]
MAX_CLOUD_COVER_LIMIT = 30.0
MAX_CLOUD_COVER_STEP = 5.0

ACTION_FIELD_MAP = {
    "expand_date_range": {"start_date", "end_date"},
    "increase_max_cloud_cover": {"max_cloud_cover"},
}


class RasterPrepareAdjustmentResult(BaseModel):
    """raster_prepare 参数调整结果。"""

    target: str = "raster_prepare"
    status: RasterPrepareAdjustmentStatus
    # `adjusted_params` 是完整的新的 `tool_call.params`，会替换目标 tool_call 的 params，
    # 不是对原 params 的局部 patch。
    adjusted_params: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    rationale: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


def adjust_raster_prepare_tool_call(
    state: AgentState,
    client: LLMClient | None = None,
) -> RasterPrepareAdjustmentResult:
    """根据 validator observation 调整上一次执行的 raster_prepare tool_call 的 params。

    语义说明：
    - 不修改 `state.plan`。
    - 修改 `state.tool_calls[last_tool_index].params` 并返回调整结果。
    """

    validation = _get_raster_prepare_validation(state)
    if validation.get("status") != "retryable":
        return RasterPrepareAdjustmentResult(
            status="skipped",
            adjusted_params={},
            rationale="raster_prepare is not in retryable status.",
        )

    suggested_actions = list(validation.get("suggested_actions", []))
    allowed_fields = _allowed_fields_from_actions(suggested_actions)
    if not allowed_fields:
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error="No supported adjustment actions were suggested.",
        )

    last_tool_index = state.runtime.get("last_tool_index")
    if last_tool_index is None:
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error="Missing last_tool_index in runtime.",
        )

    try:
        last_tool_index = int(last_tool_index)
    except (TypeError, ValueError):
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error="Invalid last_tool_index.",
        )

    if last_tool_index < 0 or last_tool_index >= len(state.tool_calls):
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error="last_tool_index out of range.",
        )

    tool_call = state.tool_calls[last_tool_index]
    if tool_call.get("id") != "raster_prepare":
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error="Last tool call is not raster_prepare.",
        )

    current_params = dict(tool_call.get("params", {}))

    try:
        raw_response = _call_adjuster_llm(
            state=state,
            validation=validation,
            client=client,
        )
        proposed_update = _parse_json_object(raw_response)
    except (RuntimeError, ValueError, OSError) as error:
        return RasterPrepareAdjustmentResult(
            status="failed",
            adjusted_params={},
            error=str(error),
        )

    adjusted_params, changed_fields = _sanitize_params_update(
        current_params=current_params,
        proposed_update=proposed_update,
        allowed_fields=allowed_fields,
    )
    if not changed_fields:
        return RasterPrepareAdjustmentResult(
            status="skipped",
            adjusted_params={},
            warnings=["LLM response did not contain any valid params adjustment."],
        )

    return RasterPrepareAdjustmentResult(
        status="adjusted",
        adjusted_params=adjusted_params,
        changed_fields=changed_fields,
        rationale=proposed_update.get("rationale"),
    )


def build_raster_prepare_adjustment_update(
    state: AgentState,
    result: RasterPrepareAdjustmentResult,
) -> dict[str, Any]:
    """把 adjuster 结果转换成 LangGraph state update。"""
    retry_count = _get_retry_count(state) + (1 if result.status == "adjusted" else 0)

    update: dict[str, Any] = {
        "runtime": {
            "adjusters": {"raster_prepare": result.model_dump(mode="json")},
            "retry_counts": {"raster_prepare": retry_count},
        }
    }

    if result.status == "adjusted":
        # update the tool_call params at last_tool_index and reset current_tool_index
        last_tool_index = state.runtime.get("last_tool_index")
        try:
            idx = int(last_tool_index)
        except (TypeError, ValueError):
            idx = None

        if idx is None or idx < 0 or idx >= len(state.tool_calls):
            # cannot apply adjustment because index invalid
            update["status"] = "failed"
            update["errors"] = ["last_tool_index invalid when applying adjustment"]
            return update

        # copy tool_calls and apply adjusted params
        new_tool_calls = [dict(item) for item in state.tool_calls]
        old_params = dict(new_tool_calls[idx].get("params", {}))
        new_tool_calls[idx]["params"] = result.adjusted_params

        # ensure id still matches
        if new_tool_calls[idx].get("id") != "raster_prepare":
            update["status"] = "failed"
            update["errors"] = ["tool_call id mismatch when applying adjustment"]
            return update

        # build adjustment record: only include changed fields in "to"
        adjustment_record = {
            "tool_call_id": new_tool_calls[idx].get("id"),
            "tool_index": idx,
            "reason": result.rationale,
            "changed_fields": result.changed_fields,
            "from": {k: old_params.get(k) for k in result.changed_fields},
            "to": {k: result.adjusted_params.get(k) for k in result.changed_fields},
        }

        existing_adjustments = state.runtime.get("adjustments")
        if not isinstance(existing_adjustments, list):
            existing_adjustments = []

        update["tool_calls"] = new_tool_calls
        update["runtime"]["current_tool_index"] = idx
        update["runtime"]["adjustments"] = list(existing_adjustments) + [
            adjustment_record
        ]
        update["status"] = "raster_prepare_adjusted"

        return update

    if result.status == "skipped":
        update["status"] = "raster_prepare_adjustment_skipped"
        if result.warnings:
            update["warnings"] = result.warnings
        return update

    # failed
    update["status"] = "failed"
    update["errors"] = [result.error or "raster_prepare_adjustment_failed"]
    return update


def _call_adjuster_llm(
    state: AgentState,
    validation: dict[str, Any],
    client: LLMClient | None,
) -> str:
    messages = _build_adjuster_messages(state, validation)
    if client is not None:
        return client(messages)

    return _call_zhipuai_chat(messages)


def _call_zhipuai_chat(messages: list[dict[str, str]]) -> str:
    settings = get_zhipuai_settings()
    if not settings.api_key:
        raise RuntimeError(
            "Missing ZHIPUAI_API_KEY. Add it to .env before calling adjuster."
        )

    url = f"{settings.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Invalid ZhipuAI chat response.") from error


def _build_adjuster_messages(
    state: AgentState,
    validation: dict[str, Any],
) -> list[dict[str, str]]:
    last_tool_index = state.runtime.get("last_tool_index")
    tool_call: dict[str, Any] | None = None
    current_params: dict[str, Any] | None = None
    try:
        if last_tool_index is not None:
            idx = int(last_tool_index)
            if 0 <= idx < len(state.tool_calls):
                tool_call = state.tool_calls[idx]
                current_params = dict(tool_call.get("params", {}))
    except (TypeError, ValueError, IndexError):
        tool_call = None

    context = {
        "user_query": state.user_query,
        "current_tool_call": tool_call,
        "current_params": current_params,
        "validation": validation,
        "retry_count": _get_retry_count(state),
        "allowed_actions": validation.get("suggested_actions", []),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是一个遥感栅格数据准备参数调整器。"
                "你只能返回一个 JSON object，不要输出 Markdown 或解释性正文。"
                "你只能根据 suggested_actions 调整必要参数。"
                "不要修改用户请求的指数、AOI、workspace 或 data_source。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请根据当前 tool_call 参数和 validator 结果，给出下一轮 "
                "raster_prepare tool_call.params 的调整建议。"
                "允许修改的字段只有 start_date、end_date、max_cloud_cover。"
                "不要修改 aoi_query、index_name、workspace_dir、data_source、"
                "scene_limit 或 max_selected_scenes。日期必须使用 YYYY-MM-DD 格式。"
                "优先扩大时间范围，尤其优先把 start_date 往前调整；尽量不要修改 max_cloud_cover。"
                "只有在确实需要时，才可以小幅提高 max_cloud_cover；max_cloud_cover 只能递增，不能降低，并且不得超过 30。"
                "请包含一个简短 rationale 字段说明原因。\n\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}"
            ),
        },
    ]


def _parse_json_object(raw_response: str) -> dict[str, Any]:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("LLM response is not valid JSON.") from error

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object.")

    return parsed


def _sanitize_params_update(
    current_params: dict[str, Any],
    proposed_update: dict[str, Any],
    allowed_fields: set[str],
) -> tuple[dict[str, Any], list[str]]:
    adjusted_params = dict(current_params)
    changed_fields: list[str] = []

    for field in sorted(allowed_fields):
        if field not in proposed_update:
            continue

        value = _sanitize_field_value(
            field=field,
            proposed_value=proposed_update[field],
            current_params=current_params,
            adjusted_params=adjusted_params,
        )
        if value is None or value == current_params.get(field):
            continue

        adjusted_params[field] = value
        changed_fields.append(field)

    return adjusted_params, changed_fields


def _sanitize_field_value(
    field: str,
    proposed_value: Any,
    current_params: dict[str, Any],
    adjusted_params: dict[str, Any],
) -> Any:
    if field in {"start_date", "end_date"}:
        return _sanitize_date(proposed_value)

    if field == "max_cloud_cover":
        current_value = float(current_params.get(field, 0))
        proposed_float = _clamp_float(
            proposed_value,
            minimum=0,
            maximum=MAX_CLOUD_COVER_LIMIT,
        )
        if proposed_float is None:
            return None
        max_next_value = min(
            current_value + MAX_CLOUD_COVER_STEP,
            MAX_CLOUD_COVER_LIMIT,
        )
        return min(max(current_value, proposed_float), max_next_value)

    return None


def _sanitize_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

    return parsed.isoformat()


def _clamp_float(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return min(max(number, minimum), maximum)


def _get_raster_prepare_validation(state: AgentState) -> dict[str, Any]:
    validators = state.runtime.get("validators", {})
    validation = validators.get("raster_prepare", {})
    if isinstance(validation, dict):
        return validation

    return {}


def _allowed_fields_from_actions(actions: list[str]) -> set[str]:
    allowed_fields: set[str] = set()
    for action in actions:
        allowed_fields.update(ACTION_FIELD_MAP.get(action, set()))

    return allowed_fields


def _get_retry_count(state: AgentState) -> int:
    retry_counts = state.runtime.get("retry_counts", {})
    return int(retry_counts.get("raster_prepare", 0))
