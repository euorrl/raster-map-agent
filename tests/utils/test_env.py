import pytest

from app.utils.env import get_zhipuai_settings, require_zhipuai_api_key


def test_get_zhipuai_settings_uses_defaults(monkeypatch):
    monkeypatch.setattr("app.utils.env.load_dotenv", lambda: None)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_MODEL", raising=False)
    monkeypatch.delenv("ZHIPUAI_BASE_URL", raising=False)

    settings = get_zhipuai_settings()

    assert settings.api_key is None
    assert settings.model == "glm-4.7-flash"
    assert settings.base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_get_zhipuai_settings_reads_environment(monkeypatch):
    monkeypatch.setattr("app.utils.env.load_dotenv", lambda: None)
    monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
    monkeypatch.setenv("ZHIPUAI_MODEL", "custom-model")
    monkeypatch.setenv("ZHIPUAI_BASE_URL", "https://example.test/v4")

    settings = get_zhipuai_settings()

    assert settings.api_key == "test-key"
    assert settings.model == "custom-model"
    assert settings.base_url == "https://example.test/v4"


def test_require_zhipuai_api_key_rejects_missing_key(monkeypatch):
    monkeypatch.setattr("app.utils.env.load_dotenv", lambda: None)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing ZHIPUAI_API_KEY"):
        require_zhipuai_api_key()
