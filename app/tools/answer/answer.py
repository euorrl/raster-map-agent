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


def generate_final_answer(
    request: FinalAnswerRequest,
    client: AnswerLLMClient | None = None,
) -> FinalAnswerResult:
    """根据 answer mode 生成最终用户回答。"""

    logger.info("Generating final answer mode=%s", request.answer_mode)

    try:
        raw_response = _call_answer_llm(request, client)
        parsed_response = _parse_json_object(raw_response)
        final_answer = _sanitize_final_answer(parsed_response)
    except (RuntimeError, ValueError, OSError) as error:
        raise FinalAnswerError(str(error)) from error

    return FinalAnswerResult(final_answer=final_answer)


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
        task_prompt = (
            "用户问题与栅格地图 workflow 无关，或者当前系统暂不支持该产品。"
            "请直接回答用户问题。若问题是在请求一个未注册的地图产品，"
            "请说明当前暂不支持，并尽量指出当前回答基于已有能力范围。"
            "\n\n"
            f"question:\n{request.question}"
        )
    else:
        context = {
            "user_query": request.user_query,
            "metadata": request.metadata,
        }
        task_prompt = (
            "请根据 workflow metadata 生成最终用户回答。回答应简洁说明任务结果、"
            "核心参数、主要输出文件和任何重要警告。不要编造 metadata 中不存在的文件、"
            "指标或结论。如果 workflow metadata 显示失败或缺少结果，请清楚说明原因。"
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
