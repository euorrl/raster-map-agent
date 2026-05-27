import os

from dotenv import load_dotenv
from pydantic import BaseModel


DEFAULT_ZHIPUAI_MODEL = "glm-4.7-flash"
DEFAULT_ZHIPUAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class ZhipuAISettings(BaseModel):
    """智谱 AI 调用配置。"""

    api_key: str | None
    model: str = DEFAULT_ZHIPUAI_MODEL
    base_url: str = DEFAULT_ZHIPUAI_BASE_URL


def get_zhipuai_settings() -> ZhipuAISettings:
    """读取本地 .env 或系统环境变量中的智谱 AI 配置。"""

    load_dotenv()
    return ZhipuAISettings(
        api_key=os.getenv("ZHIPUAI_API_KEY"),
        model=os.getenv("ZHIPUAI_MODEL", DEFAULT_ZHIPUAI_MODEL),
        base_url=os.getenv("ZHIPUAI_BASE_URL", DEFAULT_ZHIPUAI_BASE_URL),
    )


def require_zhipuai_api_key() -> str:
    """读取智谱 API Key，缺失时给出清晰错误。"""

    settings = get_zhipuai_settings()
    if not settings.api_key:
        raise RuntimeError(
            "Missing ZHIPUAI_API_KEY. Add it to .env or set it in your "
            "environment for calling the LLM."
        )

    return settings.api_key
