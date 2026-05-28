import json
from datetime import date, datetime
from typing import Any, Callable, Literal, cast
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.registry import INDEX_REGISTRY
from app.utils import get_zhipuai_settings

AgentPlanStatus = Literal["planned", "failed"]
AgentResponseMode = Literal["raster_workflow", "direct_answer"]
PlannerLLMClient = Callable[[list[dict[str, str]]], str]
MAX_INITIAL_CLOUD_COVER = 30.0
DEFAULT_INITIAL_CLOUD_COVER = 20.0
PLAN_FIELDS = {
    "response_mode",
    "aoi_query",
    "index_name",
    "start_date",
    "end_date",
    "max_cloud_cover",
}
RESPONSE_MODES = {"raster_workflow", "direct_answer"}
SUPPORTED_TOOL_NAMES = {
    "workspace.create_workspace",
    "raster_prepare.prepare_raster_inputs",
    "index_calculation.calculate_raster_index",
    "render_preview.render_index_preview",
    "metadata.export_metadata",
    "answer.generate_final_answer",
}
TOOL_CONTRACTS: list[dict[str, Any]] = [
    {
        "tool": "workspace.create_workspace",
        "purpose": "Create an isolated workspace directory for one run.",
        "inputs": [],
        "outputs": ["workspace.run_id", "workspace.workspace_dir"],
    },
    {
        "tool": "raster_prepare.prepare_raster_inputs",
        "purpose": (
            "Resolve AOI, search/select suitable scenes, and prepare raster "
            "inputs for the selected registered index."
        ),
        "inputs": [
            "aoi_query",
            "index_name",
            "start_date",
            "end_date",
            "max_cloud_cover",
        ],
        "outputs": [
            "tool_results.raster_prepare.band_paths",
            "tool_results.raster_prepare.selected_scenes",
        ],
    },
    {
        "tool": "index_calculation.calculate_raster_index",
        "purpose": "Calculate the selected raster index inside the workspace.",
        "inputs": ["workspace_dir", "index_name"],
        "outputs": ["tool_results.index_calculation.index_tif_path"],
    },
    {
        "tool": "render_preview.render_index_preview",
        "purpose": "Render the calculated index GeoTIFF as a visual preview image.",
        "inputs": ["index_name", "index_tif_path"],
        "outputs": ["tool_results.render_preview.preview_path"],
    },
    {
        "tool": "metadata.export_metadata",
        "purpose": "Export run metadata for auditing and final answer generation.",
        "inputs": ["workspace_dir", "metadata"],
        "outputs": ["tool_results.metadata.metadata_path", "metadata"],
    },
    {
        "tool": "answer.generate_final_answer",
        "purpose": (
            "Generate the final answer. Use metadata_summary mode after a raster "
            "workflow, or direct_answer mode for unrelated/general questions."
        ),
        "inputs": [
            "metadata_summary: user_query, metadata",
            "direct_answer: question",
        ],
        "outputs": ["final_answer"],
    },
]


class AgentPlanRequest(BaseModel):
    """全局 planner 请求。

    Attributes:
        user_query: 用户原始自然语言需求。
    """

    user_query: str = Field(min_length=1)


class AgentPlanResult(BaseModel):
    """全局 planner 输出结果。

    planner 只负责产出结构化计划，不执行任何真实工具。
    """

    status: AgentPlanStatus
    plan: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
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
        tool_calls = _sanitize_tool_calls(parsed_response, plan, warnings)
    except (RuntimeError, ValueError, OSError) as error:
        return AgentPlanResult(status="failed", error=str(error))

    return AgentPlanResult(
        status="planned",
        plan=plan,
        tool_calls=tool_calls,
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
            "tool_plan": {
                "steps": result.tool_calls,
            },
        }
    }

    if result.status == "planned":
        update["plan"] = result.plan
        update["metadata"] = {"plan": result.plan}
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
        "tool_contracts": TOOL_CONTRACTS,
        "max_cloud_cover_limit": MAX_INITIAL_CLOUD_COVER,
    }
    system_prompt = (
        "你是 raster-map-agent 的全局任务规划器。"
        "你的职责是把用户的自然语言需求转换成 V1 workflow 可执行的结构化 JSON 计划。"
        "你只负责规划，不执行工具，不编造注册表之外的产品，不生成最终回答正文。"
        "你必须只返回一个 JSON object，不要输出 Markdown、解释段落或代码块。"
    )
    user_prompt = (
        "请根据用户需求生成结构化规划。JSON 必须包含三个顶层字段："
        "plan、tool_calls、rationale。\n\n"
        "一、输出结构\n"
        "plan 只能包含以下字段：\n"
        "- response_mode：只能是 raster_workflow 或 direct_answer。\n"
        "- aoi_query：适合 Nominatim 查询的地点字符串，例如 "
        '"Chengdu, Sichuan, China"。\n'
        "- index_name：从 context.supported_indexes 中选择的已注册栅格产品或指数名称。\n"
        "- start_date：YYYY-MM-DD 格式。\n"
        "- end_date：YYYY-MM-DD 格式。\n"
        "- max_cloud_cover：初始优先使用 20，不得超过 context.max_cloud_cover_limit。\n\n"
        "当 response_mode 是 direct_answer 时，plan 只需要包含 response_mode。\n"
        "当 response_mode 是 raster_workflow 时，plan 必须包含全部栅格任务字段："
        "aoi_query、index_name、start_date、end_date、max_cloud_cover。\n\n"
        "tool_calls 是工具调用计划列表，每一步必须包含 tool 和 params。"
        "params 可以为空对象，系统会根据清洗后的 plan 生成最终可信参数。"
        "rationale 用一句话说明为什么选择该 response_mode、index_name 和日期范围。\n\n"
        "二、response_mode 选择规则\n"
        "1. 如果用户请求的是已注册栅格产品、遥感指数、专题图生成、地图生成、"
        "地理区域分析，并且可以由注册表中的某个选项完成，选择 raster_workflow。\n"
        "2. 如果用户的问题与当前栅格地图 workflow 无关，或者只是普通知识问答、"
        "闲聊、解释概念、询问系统能力，选择 direct_answer。\n"
        "3. 如果用户请求 population、land type、land cover、temperature "
        "等当前注册表中不存在的产品，选择 direct_answer，让最终回答节点说明当前不支持，"
        "不要强行映射到 NDVI/NDWI，也不要运行错误的栅格 workflow。\n\n"
        "三、index_name 选择规则\n"
        "1. 不要默认选择 NDVI。必须根据用户任务语义和 context.registered_options 选择。\n"
        "2. 如果用户明确要求某个已注册选项，就选择该选项。\n"
        "3. 如果用户没有明确给出产品名，请结合注册选项的名称、公式、波段角色和渲染信息，"
        "从已注册选项中推断最匹配的一个。\n"
        "4. 植被、长势、绿度、作物健康相关任务通常匹配 NDVI，前提是 NDVI 已注册。\n"
        "5. 水体、地表水、湿度、水域提取相关任务通常匹配 NDWI，前提是 NDWI 已注册。\n"
        "6. 如果没有任何已注册选项明确满足用户任务，选择 direct_answer，不要编造 index_name。\n\n"
        "四、日期推断优先级\n"
        "1. 用户给出完整日期范围时，优先严格使用用户日期，但不得选择未来日期。\n"
        "2. 用户只给出年份、月份、季节或类似“2024 年”“去年夏天”“今年春季”的模糊时间时，"
        "要补全成合理的 start_date 和 end_date。\n"
        "   - 指定年份但未指定月份/季节时，根据专题图类型选择该年份内最合理的窗口；"
        "NDVI/植被优先使用当地生长季，NDWI/水体优先使用水体可观测性较稳定的季节或近季节窗口。\n"
        "   - 指定月份时，使用该月第一天到该月最后一天。\n"
        "   - 指定季节时，北半球春季 3-5 月、夏季 6-8 月、秋季 9-11 月、冬季 12-2 月；"
        "南半球季节相反。跨年冬季要正确处理年份。\n"
        "3. 用户完全没有给时间时，根据专题图类型选择靠近 context.current_date、"
        "完整且不在未来的合理日期范围。\n"
        "   - NDVI/植被：优先最近一个完整生长季；如果当前生长季尚未完整结束，"
        "使用上一完整生长季。\n"
        "   - NDWI/水体：优先最近一个完整的 1-3 个月观测窗口，避免未来日期。\n"
        "   - 其他已注册产品：根据产品语义选择最近的完整可观测窗口。\n"
        "4. 如果推断出的 end_date 晚于 context.current_date，必须改用最近一个已经完整结束的合理窗口。\n\n"
        "五、工具能力、输入和输出\n"
        "请参考 context.tool_contracts。各工具含义如下：\n"
        "- workspace.create_workspace：创建本次任务工作目录；输入无；"
        "输出 workspace.run_id 和 workspace.workspace_dir。\n"
        "- raster_prepare.prepare_raster_inputs：根据 AOI、指数、日期、云量检索并准备栅格输入；"
        "输入 aoi_query、index_name、start_date、end_date、max_cloud_cover；"
        "输出准备好的波段路径和场景信息。\n"
        "- index_calculation.calculate_raster_index：计算指定指数；"
        "输入 workspace_dir、index_name；输出 index_tif_path。\n"
        "- render_preview.render_index_preview：渲染指数预览图；"
        "输入 index_name、index_tif_path；输出 preview_path。\n"
        "- metadata.export_metadata：导出任务元数据；"
        "输入 workspace_dir、metadata；"
        "输出 metadata_path 和 metadata。\n"
        "- answer.generate_final_answer：生成最终回答；"
        "metadata_summary 模式使用 user_query 和 metadata，direct_answer 模式使用 question。\n\n"
        "六、工具顺序规则\n"
        "1. raster_workflow 的默认顺序是：workspace.create_workspace -> "
        "raster_prepare.prepare_raster_inputs -> "
        "index_calculation.calculate_raster_index -> "
        "render_preview.render_index_preview -> metadata.export_metadata -> "
        "answer.generate_final_answer。\n"
        "2. direct_answer 只需要 answer.generate_final_answer。\n"
        "3. tool 只能从 context.tool_contracts 中列出的名称选择。\n"
        "4. 不要把工具内部参数写进 plan，例如 data_source、need_render、include_colorbar、"
        "need_metadata、scene_limit、max_selected_scenes、workspace_dir。\n\n"
        "七、示例\n"
        "用户问“生成成都 2024 年 NDVI 图”：选择 raster_workflow，"
        "index_name 为 NDVI，日期根据 2024 年植被专题补成合理生长季。\n"
        "用户问“什么是遥感”：选择 direct_answer。\n"
        "用户问“生成成都人口密度图”，但 population 未注册：选择 direct_answer，"
        "不要改成 NDVI 或 NDWI。\n\n"
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
    response_mode = _sanitize_response_mode(raw_plan.get("response_mode"))
    if response_mode == "direct_answer":
        plan = {
            "response_mode": response_mode,
        }
        ignored_fields = sorted(
            set(raw_plan) - PLAN_FIELDS - {"rationale", "tool_calls"}
        )
        if ignored_fields:
            ignored_field_names = ", ".join(ignored_fields)
            warnings.append(
                f"Ignored unsupported planner fields: {ignored_field_names}."
            )

        return plan, warnings

    plan = {
        "response_mode": response_mode,
        "aoi_query": _sanitize_aoi_query(raw_plan, request, warnings),
        "index_name": _sanitize_index_name(raw_plan.get("index_name")),
        "start_date": _sanitize_date(raw_plan.get("start_date"), "start_date"),
        "end_date": _sanitize_date(raw_plan.get("end_date"), "end_date"),
        "max_cloud_cover": _sanitize_cloud_cover(raw_plan.get("max_cloud_cover")),
    }

    if plan["start_date"] > plan["end_date"]:
        raise ValueError("Planner start_date cannot be later than end_date.")

    ignored_fields = sorted(set(raw_plan) - PLAN_FIELDS - {"rationale", "tool_calls"})
    if ignored_fields:
        ignored_field_names = ", ".join(ignored_fields)
        warnings.append(f"Ignored unsupported planner fields: {ignored_field_names}.")

    return plan, warnings


def _sanitize_tool_calls(
    parsed_response: dict[str, Any],
    plan: dict[str, Any],
    warnings: list[str],
) -> list[dict[str, Any]]:
    if plan.get("response_mode") == "direct_answer":
        return [
            {
                "step": 1,
                "tool": "answer.generate_final_answer",
                "params": _canonical_tool_params(
                    "answer.generate_final_answer",
                    plan,
                ),
            }
        ]

    raw_tool_calls = parsed_response.get("tool_calls")
    nested_plan = parsed_response.get("plan")
    if raw_tool_calls is None and isinstance(nested_plan, dict):
        raw_tool_calls = nested_plan.get("tool_calls")

    if not isinstance(raw_tool_calls, list) or not raw_tool_calls:
        warnings.append(
            "Planner did not provide tool_calls; default V1 tool order was used."
        )
        return _default_tool_calls(plan)

    tool_calls: list[dict[str, Any]] = []
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            warnings.append("Ignored invalid planner tool call.")
            continue

        tool_name = item.get("tool")
        if tool_name not in SUPPORTED_TOOL_NAMES:
            warnings.append(f"Ignored unsupported planner tool: {tool_name}.")
            continue

        tool_calls.append(
            {
                "step": len(tool_calls) + 1,
                "tool": tool_name,
                "params": _canonical_tool_params(tool_name, plan),
            }
        )

    if not tool_calls:
        warnings.append(
            "Planner tool_calls were unusable; default V1 tool order was used."
        )
        return _default_tool_calls(plan)

    return tool_calls


def _default_tool_calls(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("response_mode") == "direct_answer":
        return [
            {
                "step": 1,
                "tool": "answer.generate_final_answer",
                "params": _canonical_tool_params(
                    "answer.generate_final_answer",
                    plan,
                ),
            }
        ]

    return [
        {
            "step": index + 1,
            "tool": tool_name,
            "params": _canonical_tool_params(tool_name, plan),
        }
        for index, tool_name in enumerate(
            [
                "workspace.create_workspace",
                "raster_prepare.prepare_raster_inputs",
                "index_calculation.calculate_raster_index",
                "render_preview.render_index_preview",
                "metadata.export_metadata",
                "answer.generate_final_answer",
            ]
        )
    ]


def _canonical_tool_params(tool_name: str, plan: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "workspace.create_workspace":
        return {}

    if tool_name == "raster_prepare.prepare_raster_inputs":
        return {
            "aoi_query": plan["aoi_query"],
            "index_name": plan["index_name"],
            "start_date": plan["start_date"],
            "end_date": plan["end_date"],
            "max_cloud_cover": plan["max_cloud_cover"],
        }

    if tool_name == "index_calculation.calculate_raster_index":
        return {
            "workspace_dir": "$workspace.workspace_dir",
            "index_name": plan["index_name"],
        }

    if tool_name == "render_preview.render_index_preview":
        return {
            "index_name": plan["index_name"],
            "index_tif_path": "$tool_results.index_calculation.index_tif_path",
        }

    if tool_name == "metadata.export_metadata":
        return {
            "workspace_dir": "$workspace.workspace_dir",
            "metadata": "$metadata",
        }

    if tool_name == "answer.generate_final_answer":
        if plan.get("response_mode") == "direct_answer":
            return {
                "answer_mode": "direct_answer",
                "question": "$state.user_query",
            }

        return {
            "answer_mode": "metadata_summary",
            "user_query": "$state.user_query",
            "metadata": "$metadata",
        }

    return {}


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


def _sanitize_response_mode(value: Any) -> AgentResponseMode:
    if value is None:
        return "raster_workflow"

    if not isinstance(value, str):
        raise ValueError("Planner response_mode must be a string.")

    response_mode = value.strip().lower()
    if response_mode not in RESPONSE_MODES:
        supported = ", ".join(sorted(RESPONSE_MODES))
        raise ValueError(
            f"Unsupported planner response_mode: {value}. Supports: {supported}"
        )

    return cast(AgentResponseMode, response_mode)


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
