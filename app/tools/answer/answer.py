import json
from typing import Callable
from urllib.request import Request, urlopen

from app.tools.answer.schemas import (
    FinalAnswerError,
    FinalAnswerRequest,
    FinalAnswerResult,
)
from app.utils import get_zhipuai_settings
from app.utils.logging import get_logger

AnswerLLMClient = Callable[[list[dict[str, str]]], str]

logger = get_logger(__name__)

AGENT_CAPABILITY_KEYWORDS = (
    "你是",
    "你谁",
    "您是谁",
    "您谁",
    "你是什么",
    "您是什么",
    "你如何使用",
    "您如何使用",
    "你是干",
    "您是干",
    "你是做",
    "您是做",
    "你是什么",
    "你的功能",
    "你的能力",
    "你有哪些功能",
    "你有哪些能力",
    "你支持什么",
    "你支持哪些",
    "你能做什么",
    "你可以做什么",
    "可以做什么",
    "能做什么",
    "能帮我做什么",
    "能帮我什么",
    "能处理什么",
    "可以处理什么",
    "支持哪些任务",
    "支持什么任务",
    "有什么功能",
    "有什么能力",
    "功能介绍",
    "能力介绍",
    "使用说明",
    "怎么使用你",
    "如何使用你",
    "介绍一下你",
    "介绍一下自己",
    "介绍你",
    "介绍下你",
    "介绍下自己",
    "自我介绍",
    "关于你",
    "这个系统能做什么",
    "这个助手能做什么",
    "这个工具能做什么",
    "raster map agent",
    "raster-map-agent",
    "what are you",
    "who are you",
    "what can you do",
    "what do you do",
    "your capabilities",
    "your functions",
    "how to use you",
    "how can i use you",
    "introduce yourself",
    "tell me about yourself",
    "what is raster-map-agent",
    "what is raster map agent",
)

AGENT_PROFILE_ANSWER = (
    "我是 raster-map-agent，一个面向栅格遥感产品生成的工作流助手。\n\n"
    "我当前主要能做三件事：\n"
    "1. 根据用户给出的地点、时间范围，规划栅格产品生成任务。\n"
    "2. 调用已注册的栅格产品流程生成专题图，目前以注册表中的产品为准，"
    "包括 NDVI（植被绿度）、SAVI（稀疏植被 / 土壤背景校正）、"
    "NDWI（水体）、NDMI（水分 / 湿度）、NDBI（建成区）和 "
    "NBR（火烧迹地 / 植被受损）。\n"
    "3. 根据生成后的产品信息，简要说明数据来源、时间范围、空间信息和"
    "重要警告；如果任务失败，我会说明失败原因并给出可调整方向。\n\n"
    "我不会凭空承诺未接入的产品能力。比如 population、DEM、night lights、"
    "landtype / land cover 等产品如果还没有注册，我会说明当前暂不支持，"
    "而不是强行映射成已有指数。\n\n"
    "当前支持的示例产品：\n"
    "- NDVI：查看植被绿度和覆盖情况。\n"
    "- SAVI：查看稀疏植被区域，适合裸土背景较强的地方。\n"
    "- NDWI：查看水体和水域分布。\n"
    "- NDMI：查看植被含水量、地表湿度或干旱胁迫。\n"
    "- NDBI：查看建成区、不透水面或城市扩张特征。\n"
    "- NBR：查看火烧迹地、火灾影响或植被受损情况。\n\n"
    "可运行示例：\n"
    "你有哪些功能\n"
    "我想看看成都最近的植被分布如何\n"
    "能帮我生成一张巴黎 2026 年的水域分布图吗\n"
    "我想看看 2026 年米兰的建成区\n"
    "注意！不支持面积过大的请求，推荐小于10万平方公里的区域，"
    "过大的请求可能会失败，并且区域越大生成时间越长。\n\n"
    "English version:\n"
    "I am raster-map-agent, a workflow assistant for generating raster "
    "remote-sensing products.\n\n"
    "I can currently help with three main tasks:\n"
    "1. Plan raster product generation from a user-provided place and "
    "time range.\n"
    "2. Run registered raster product workflows to generate thematic maps. "
    "The available products are defined by the registry, including NDVI "
    "for vegetation greenness, SAVI for sparse vegetation with soil-background "
    "adjustment, NDWI for water, NDMI for moisture, NDBI for built-up areas, "
    "and NBR for burned areas or vegetation damage.\n"
    "3. Summarize the generated product information, including data source, "
    "time range, spatial information, and important warnings. If the task "
    "fails, I will explain the failure and suggest how to adjust the request."
    "\n\n"
    "I will not claim unsupported product capabilities. For example, if "
    "population, DEM, night lights, landtype, or land cover products have "
    "not been registered, I will say they are not supported yet instead of "
    "forcing them into an existing index.\n\n"
    "Currently supported example products:\n"
    "- NDVI: vegetation greenness and coverage.\n"
    "- SAVI: sparse vegetation, especially where soil background is strong.\n"
    "- NDWI: water and surface water distribution.\n"
    "- NDMI: vegetation moisture, surface wetness, or drought stress.\n"
    "- NDBI: built-up areas, impervious surfaces, or urban expansion.\n"
    "- NBR: burned areas, fire impact, or vegetation damage.\n\n"
    "Runnable examples:\n"
    "what can you do\n"
    "I want to see the recent vegetation distribution in Chengdu\n"
    "Can you generate a water distribution map of Paris for 2026\n"
    "I want to see the built-up area of Milan in 2026\n"
    "Attention! Requests with large areas are not supported."
    "We recommend areas smaller than 100000 square kilometers.\n"
    "Requests that are too large may fail, and the larger the region, "
    "the longer the generation time."
)


def generate_final_answer(
    request: FinalAnswerRequest,
    client: AnswerLLMClient | None = None,
) -> FinalAnswerResult:
    """根据 answer_mode 生成最终用户回答。"""

    logger.info("Generating final answer mode=%s", request.answer_mode)

    if _should_return_agent_profile(request):
        return FinalAnswerResult(final_answer=AGENT_PROFILE_ANSWER)

    try:
        raw_response = _call_answer_llm(request, client)
        parsed_response = _parse_json_object(raw_response)
        final_answer = _sanitize_final_answer(parsed_response)
    except (RuntimeError, ValueError, OSError) as error:
        raise FinalAnswerError(str(error)) from error

    return FinalAnswerResult(final_answer=final_answer)


def _should_return_agent_profile(request: FinalAnswerRequest) -> bool:
    return (
        request.answer_mode == "direct_answer"
        and _infer_direct_answer_task(request.question or "") == "agent_profile"
    )


def _call_answer_llm(
    request: FinalAnswerRequest,
    client: AnswerLLMClient | None,
) -> str:
    messages = _build_answer_messages(request)
    if client is not None:
        return client(messages)

    return _call_zhipuai_chat(messages)


def _call_zhipuai_chat(messages: list[dict[str, str]]) -> str:
    settings = get_zhipuai_settings()
    if not settings.api_key:
        raise RuntimeError(
            "Missing ZHIPUAI_API_KEY. Add it to .env before calling answer tool."
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


def _build_answer_messages(request: FinalAnswerRequest) -> list[dict[str, str]]:
    if request.answer_mode == "direct_answer":
        direct_answer_task = _infer_direct_answer_task(request.question or "")
        task_prompt = (
            "请根据 direct_answer_task 生成最终回答。\n"
            "- 如果 direct_answer_task 是 agent_profile：介绍 raster-map-agent "
            "是什么、能做什么、当前适合处理哪些栅格地图任务，并给出一个"
            "可运行的用户提问示例。不要声称已经执行工具。\n"
            "- 如果 direct_answer_task 是 general_answer：直接回答用户问题；"
            "如果用户请求未注册或暂不支持的地图产品，请说明当前暂不支持，"
            "并提示用户可以提问<你有什么功能>\n\n"
            f"direct_answer_task: {direct_answer_task}\n"
            "\n\n"
            f"question:\n{request.question}"
        )
    else:
        context = {
            "user_query": request.user_query,
            "metadata": request.metadata,
            "metadata_has_failure": _metadata_has_failure(request.metadata),
        }
        task_prompt = (
            "请根据 workflow metadata 生成最终用户回答。\n"
            "- 正常完成时：回答要简要，优先说明产品名称/类型、区域、时间范围、"
            "数据来源、分辨率、CRS、云量等 metadata 中真实存在的关键信息；"
            "不要编造文件、指标、结论或不存在的路径。\n"
            "- 如果 metadata_has_failure 为 true，或 metadata 中存在 status=failed、"
            "errors、失败诊断、缺少关键结果：回答要更详细，说明失败阶段、"
            "失败原因、已知上下文、用户可以如何调整请求，并提供一个正常运行"
            "的示例，例如：我想看看 2026 年米兰的建成区。\n"
            "- 如果只有警告没有失败：简要说明结果，并补充警告含义。\n"
            "返回的信息应该每一条都基于 metadata 中真实存在的字段，不要编造不存在的内容。\n"
            "返回的格式应该是首先简单介绍这个产品是什么以及为什么选择这个产品，"
            "然后列出 metadata 中的关键信息，例如产品名称/类型、区域、时间范围、数据来源、分辨率、CRS、云量等。"
            "返回正常回答时后面同时输出一版英文版本，格式同上，但用英文表达。\n\n"
            "\n\n"
            f"context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    return [
        {
            "role": "system",
            "content": (
                "你是 raster-map-agent 的最终回答生成器。"
                "你只负责生成最终面向用户的回答，不执行工具。"
                "必须只返回一个 JSON object，格式为 "
                '{"final_answer": "..."}。不要输出 Markdown 代码块。'
            ),
        },
        {
            "role": "user",
            "content": task_prompt,
        },
    ]


def _infer_direct_answer_task(question: str) -> str:
    normalized = question.strip().lower()
    if any(keyword in normalized for keyword in AGENT_CAPABILITY_KEYWORDS):
        return "agent_profile"

    return "general_answer"


def _metadata_has_failure(metadata: dict) -> bool:
    if not metadata:
        return True

    status = metadata.get("status")
    if isinstance(status, str) and status.lower() in {"failed", "error"}:
        return True

    for key in ("errors", "error", "failure", "diagnostics"):
        value = metadata.get(key)
        if _contains_failure_signal(value):
            return True

    return False


def _contains_failure_signal(value) -> bool:
    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, list):
        return any(_contains_failure_signal(item) for item in value)

    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str) and status.lower() in {"failed", "error"}:
            return True
        return any(
            _contains_failure_signal(item)
            for key, item in value.items()
            if key in {"errors", "error", "failure", "message", "reason"}
        )

    return False


def _parse_json_object(raw_response: str) -> dict:
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


def _sanitize_final_answer(parsed_response: dict) -> str:
    final_answer = parsed_response.get("final_answer")
    if not isinstance(final_answer, str) or not final_answer.strip():
        raise ValueError("LLM response is missing final_answer.")

    return final_answer.strip()
