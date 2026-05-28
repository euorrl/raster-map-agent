import json
from datetime import date, datetime
from typing import Any, Callable, Literal, cast
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.registry import INDEX_REGISTRY
from app.tools.answer.schemas import AnswerMode
from app.utils import get_zhipuai_settings
from app.workflows.templates import (
    DIRECT_ANSWER_ROUTE,
    RASTER_PRODUCT_GENERATE_ROUTE,
    WorkflowRoute,
    get_workflow_route_answer_modes,
    get_workflow_template_routes,
)

AgentPlanStatus = Literal["planned", "failed"]
AgentRoute = WorkflowRoute
AgentAnswerMode = AnswerMode
PlannerLLMClient = Callable[[list[dict[str, str]]], str]

MAX_INITIAL_CLOUD_COVER = 30.0
DEFAULT_INITIAL_CLOUD_COVER = 20.0

PLAN_FIELDS = {
    "route",
    "answer_mode",
    "response_mode",  # Deprecated planner output accepted for compatibility.
    "aoi_query",
    "index_name",
    "start_date",
    "end_date",
    "max_cloud_cover",
}
ROUTES = set(get_workflow_template_routes())
ROUTE_ANSWER_MODES = get_workflow_route_answer_modes()
ANSWER_MODES = set(ROUTE_ANSWER_MODES.values())
LEGACY_RESPONSE_MODE_ROUTES: dict[str, AgentRoute] = {
    "raster_workflow": RASTER_PRODUCT_GENERATE_ROUTE,
    "direct_answer": DIRECT_ANSWER_ROUTE,
}


class AgentPlanRequest(BaseModel):
    """全局 planner 请求。"""

    user_query: str = Field(min_length=1)


class AgentPlanResult(BaseModel):
    """全局 planner 输出结果。

    Planner 只负责产出结构化 plan，不执行工具，也不生成工具调用链。
    后续 compiler 会根据 plan.route 编译 state.tool_calls。
    """

    status: AgentPlanStatus
    plan: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


def build_agent_plan(
    request: AgentPlanRequest | str,
    client: PlannerLLMClient | None = None,
) -> AgentPlanResult:
    """把用户自然语言需求转换成 V1 workflow 可执行的结构化 plan。"""

    plan_request = (
        AgentPlanRequest(user_query=request) if isinstance(request, str) else request
    )

    try:
        raw_response = _call_planner_llm(plan_request, client)
        parsed_response = _parse_json_object(raw_response)
        plan, warnings = _sanitize_plan(parsed_response, plan_request)
    except (RuntimeError, ValueError, OSError) as error:
        return AgentPlanResult(status="failed", error=str(error))

    return AgentPlanResult(
        status="planned",
        plan=plan,
        rationale=_extract_rationale(parsed_response),
        warnings=warnings,
    )


def build_agent_plan_update(result: AgentPlanResult) -> dict[str, Any]:
    """把 planner 结果转换成 LangGraph state update。"""

    update: dict[str, Any] = {
        "runtime": {
            "planners": {
                "global": result.model_dump(mode="json"),
            },
        }
    }

    if result.status == "planned":
        update["plan"] = result.plan
        update["status"] = "planned"
        if result.warnings:
            update["warnings"] = result.warnings
    else:
        update["status"] = "failed"
        update["errors"] = [result.error or "agent_planning_failed"]

    return update


def _call_planner_llm(
    request: AgentPlanRequest,
    client: PlannerLLMClient | None,
) -> str:
    messages = _build_planner_messages(request)
    if client is not None:
        return client(messages)

    return _call_zhipuai_chat(messages)


def _call_zhipuai_chat(messages: list[dict[str, str]]) -> str:
    settings = get_zhipuai_settings()
    if not settings.api_key:
        raise RuntimeError(
            "Missing ZHIPUAI_API_KEY. Add it to .env before calling planner."
        )

    url = f"{settings.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.1,
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


def _build_planner_messages(request: AgentPlanRequest) -> list[dict[str, str]]:
    context = {
        "current_date": date.today().isoformat(),
        "supported_indexes": sorted(INDEX_REGISTRY.keys()),
        "registered_options": _build_registered_option_context(),
        "workflow_routes": get_workflow_template_routes(),
        "answer_modes": sorted(ANSWER_MODES),
        "max_cloud_cover_limit": MAX_INITIAL_CLOUD_COVER,
    }
    system_prompt = (
        "你是 raster-map-agent 的全局任务规划器。"
        "你的职责是把用户自然语言需求转换成受约束的结构化 plan。"
        "你不执行工具，不决定底层工具顺序，不决定 validator、adjuster 或 retry。"
        "工具链会由系统根据 route 和 workflow template 编译。"
        "你必须只返回一个 JSON object，不要输出 Markdown、解释段落或代码块。"
    )
    user_prompt = (
        "请根据用户需求生成结构化规划。JSON 必须包含 plan 和 rationale。\n\n"
        "一、输出结构\n"
        "plan 只能包含以下字段：\n"
        "- route：只能是 raster_product_generate 或 direct_answer。\n"
        "- answer_mode：只能是 metadata_summary 或 direct_answer。\n"
        "- aoi_query：适合 Nominatim 查询的地点字符串，例如 "
        '"Chengdu, Sichuan, China"。\n'
        "- index_name：从 context.supported_indexes 中选择的已注册栅格产品或指数名称。\n"
        "- start_date：YYYY-MM-DD 格式。\n"
        "- end_date：YYYY-MM-DD 格式。\n"
        "- max_cloud_cover：初始优先使用 20，不得超过 context.max_cloud_cover_limit。\n\n"
        "当 route 是 direct_answer 时，plan 只需要包含 route 和 answer_mode。\n"
        "当 route 是 raster_product_generate 时，plan 必须包含全部栅格任务字段："
        "aoi_query、index_name、start_date、end_date、max_cloud_cover。\n\n"
        "不要输出 tool_calls。不要规划工具调用顺序。不要输出 workspace_dir、"
        "band_roles、index_formula、scene_limit、max_selected_scenes、validator、"
        "adjuster 或 retry 参数。系统会根据 route 和 workflow template 编译工具链。\n\n"
        "二、route 选择规则\n"
        "1. 如果用户请求的是已注册栅格产品、遥感指数、专题图生成、地图生成或"
        "地理区域分析，并且可以由注册表中的某个选项完成，选择 "
        "raster_product_generate，answer_mode 使用 metadata_summary。\n"
        "2. 如果用户的问题与当前栅格地图 workflow 无关，或者只是普通知识问答、"
        "闲聊、解释概念、询问系统能力，选择 direct_answer，answer_mode 使用 "
        "direct_answer。\n"
        "3. 如果用户请求 population、land type、land cover、temperature 等当前"
        "注册表中不存在的产品，选择 direct_answer，让最终回答节点说明当前不支持；"
        "不要强行映射到 NDVI/NDWI。\n\n"
        "三、index_name 选择规则\n"
        "1. 不要默认选择 NDVI，必须根据用户任务语义和 context.registered_options 选择。\n"
        "2. 如果用户明确要求某个已注册选项，就选择该选项。\n"
        "3. 植被、长势、绿度、作物健康相关任务通常匹配 NDVI，前提是 NDVI 已注册。\n"
        "4. 水体、地表水、湿度、水域提取相关任务通常匹配 NDWI，前提是 NDWI 已注册。\n"
        "5. 如果没有任何已注册选项明确满足用户任务，选择 direct_answer，不要编造 index_name。\n\n"
        "四、日期推断优先级\n"
        "1. 用户给出完整日期范围时，优先严格使用用户日期，但不得选择未来日期。\n"
        "2. 用户只给出年份、月份、季节或类似“2024 年”“去年夏天”的模糊时间时，"
        "要补全成合理的 start_date 和 end_date。\n"
        "3. 指定年份但未指定月份/季节时，根据专题图类型选择该年份内合理窗口；"
        "NDVI/植被优先生长季，NDWI/水体优先可观测性较稳定的窗口。\n"
        "4. 完全没有时间时，根据专题图类型选择靠近 context.current_date、完整且"
        "不在未来的合理日期范围。\n\n"
        "五、示例\n"
        "用户问“生成成都 2024 年 NDVI 图”：选择 raster_product_generate，"
        "answer_mode 为 metadata_summary，index_name 为 NDVI。\n"
        "用户问“什么是遥感”：选择 direct_answer，answer_mode 为 direct_answer。\n"
        "用户问“生成成都人口密度图”，但 population 未注册：选择 direct_answer。\n\n"
        f"context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        "\n\n"
        f"user_query:\n{request.user_query}"
    )
    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]


def _build_registered_option_context() -> list[dict[str, Any]]:
    return [
        {
            "index_name": index_name,
            "formula": config.index_formula,
            "data_sources": sorted(config.data_sources.keys()),
            "band_roles": {
                data_source: source_config.band_roles
                for data_source, source_config in config.data_sources.items()
            },
            "render": config.render_config.model_dump(mode="json"),
        }
        for index_name, config in sorted(INDEX_REGISTRY.items())
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


def _sanitize_plan(
    parsed_response: dict[str, Any],
    request: AgentPlanRequest,
) -> tuple[dict[str, Any], list[str]]:
    raw_plan = parsed_response.get("plan", parsed_response)
    if not isinstance(raw_plan, dict):
        raise ValueError("Planner response plan must be a JSON object.")

    warnings: list[str] = []
    route = _sanitize_route(
        route_value=raw_plan.get("route"),
        answer_mode_value=raw_plan.get("answer_mode"),
        legacy_response_mode=raw_plan.get("response_mode"),
        warnings=warnings,
    )
    answer_mode = _sanitize_answer_mode(
        value=raw_plan.get("answer_mode"),
        route=route,
        legacy_response_mode=raw_plan.get("response_mode"),
        warnings=warnings,
    )
    if route == "direct_answer":
        plan = {
            "route": route,
            "answer_mode": answer_mode,
        }
        direct_answer_fields = {"route", "answer_mode", "response_mode"}
        ignored_fields = sorted(set(raw_plan) - direct_answer_fields - {"rationale"})
        if ignored_fields:
            ignored_field_names = ", ".join(ignored_fields)
            warnings.append(
                f"Ignored unsupported planner fields: {ignored_field_names}."
            )

        return plan, warnings

    plan = {
        "route": route,
        "answer_mode": answer_mode,
        "aoi_query": _sanitize_aoi_query(raw_plan, request, warnings),
        "index_name": _sanitize_index_name(raw_plan.get("index_name")),
        "start_date": _sanitize_date(raw_plan.get("start_date"), "start_date"),
        "end_date": _sanitize_date(raw_plan.get("end_date"), "end_date"),
        "max_cloud_cover": _sanitize_cloud_cover(raw_plan.get("max_cloud_cover")),
    }

    if plan["start_date"] > plan["end_date"]:
        raise ValueError("Planner start_date cannot be later than end_date.")

    ignored_fields = sorted(set(raw_plan) - PLAN_FIELDS - {"rationale"})
    if ignored_fields:
        ignored_field_names = ", ".join(ignored_fields)
        warnings.append(f"Ignored unsupported planner fields: {ignored_field_names}.")

    return plan, warnings


def _extract_rationale(parsed_response: dict[str, Any]) -> str | None:
    rationale = parsed_response.get("rationale")
    if isinstance(rationale, str):
        return rationale

    nested_plan = parsed_response.get("plan")
    if isinstance(nested_plan, dict) and isinstance(nested_plan.get("rationale"), str):
        return nested_plan["rationale"]

    return None


def _sanitize_aoi_query(
    raw_plan: dict[str, Any],
    request: AgentPlanRequest,
    warnings: list[str],
) -> str:
    aoi_query = raw_plan.get("aoi_query")
    if isinstance(aoi_query, str) and aoi_query.strip():
        return aoi_query.strip()

    warnings.append("Planner did not provide aoi_query; user_query was used instead.")
    return request.user_query.strip()


def _sanitize_route(
    route_value: Any,
    answer_mode_value: Any,
    legacy_response_mode: Any,
    warnings: list[str],
) -> AgentRoute:
    inferred_route = _infer_route(
        answer_mode_value=answer_mode_value,
        legacy_response_mode=legacy_response_mode,
    )
    if route_value is None:
        return inferred_route or RASTER_PRODUCT_GENERATE_ROUTE

    if not isinstance(route_value, str):
        fallback_route = inferred_route or RASTER_PRODUCT_GENERATE_ROUTE
        warnings.append(f"Ignored invalid planner route; using {fallback_route}.")
        return fallback_route

    route = route_value.strip()
    if route not in ROUTES:
        fallback_route = inferred_route or RASTER_PRODUCT_GENERATE_ROUTE
        warnings.append(
            f"Ignored unsupported planner route: {route_value}; using "
            f"{fallback_route}."
        )
        return fallback_route

    if inferred_route is not None and route != inferred_route:
        warnings.append(
            f"Ignored planner route {route}; answer mode requires " f"{inferred_route}."
        )
        return inferred_route

    return cast(AgentRoute, route)


def _sanitize_answer_mode(
    value: Any,
    route: AgentRoute,
    legacy_response_mode: Any,
    warnings: list[str],
) -> AgentAnswerMode:
    expected_answer_mode = ROUTE_ANSWER_MODES[route]
    if value is None:
        return expected_answer_mode

    if not isinstance(value, str):
        warnings.append(
            f"Ignored invalid planner answer_mode; using {expected_answer_mode}."
        )
        return expected_answer_mode

    answer_mode = value.strip().lower()
    if answer_mode not in ANSWER_MODES:
        warnings.append(
            f"Ignored unsupported planner answer_mode: {value}; using "
            f"{expected_answer_mode}."
        )
        return expected_answer_mode

    if answer_mode != expected_answer_mode:
        warnings.append(
            f"Ignored planner answer_mode {answer_mode}; route {route} requires "
            f"{expected_answer_mode}."
        )
        return expected_answer_mode

    if legacy_response_mode is not None:
        warnings.append("Planner response_mode is deprecated; use answer_mode.")

    return cast(AgentAnswerMode, answer_mode)


def _infer_route(
    answer_mode_value: Any,
    legacy_response_mode: Any,
) -> AgentRoute | None:
    if isinstance(answer_mode_value, str):
        answer_mode = answer_mode_value.strip().lower()
        if answer_mode == "direct_answer":
            return DIRECT_ANSWER_ROUTE
        if answer_mode == "metadata_summary":
            return RASTER_PRODUCT_GENERATE_ROUTE

    if isinstance(legacy_response_mode, str):
        response_mode = legacy_response_mode.strip().lower()
        if response_mode in LEGACY_RESPONSE_MODE_ROUTES:
            return LEGACY_RESPONSE_MODE_ROUTES[response_mode]

    return None


def _sanitize_index_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Planner response is missing index_name.")

    index_name = value.upper()
    if index_name not in INDEX_REGISTRY:
        supported = ", ".join(sorted(INDEX_REGISTRY))
        raise ValueError(
            f"Unsupported planner index_name: {value}. Supports: {supported}"
        )

    return index_name


def _sanitize_date(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Planner response is missing {field_name}.")

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"Planner {field_name} must use YYYY-MM-DD.") from error

    return parsed.isoformat()


def _sanitize_cloud_cover(value: Any) -> float:
    if value is None:
        return DEFAULT_INITIAL_CLOUD_COVER

    try:
        cloud_cover = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Planner max_cloud_cover must be a number.") from error

    return min(max(cloud_cover, 0.0), MAX_INITIAL_CLOUD_COVER)
