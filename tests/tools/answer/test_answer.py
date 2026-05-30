import pytest
from pydantic import ValidationError

from app.tools.answer import (
    FinalAnswerError,
    FinalAnswerRequest,
    generate_final_answer,
)


def test_generate_final_answer_direct_answer_with_fake_client():
    def fake_client(messages):
        assert messages[0]["role"] == "system"
        assert "final_answer" in messages[0]["content"]
        assert "direct_answer_task: general_answer" in messages[1]["content"]
        assert "question:" in messages[1]["content"]
        assert "什么是遥感" in messages[1]["content"]
        return '{"final_answer": "遥感是通过传感器远距离获取地物信息的技术。"}'

    result = generate_final_answer(
        FinalAnswerRequest(
            answer_mode="direct_answer",
            question="什么是遥感？",
        ),
        client=fake_client,
    )

    assert result.final_answer == "遥感是通过传感器远距离获取地物信息的技术。"


def test_generate_final_answer_agent_profile_uses_fixed_answer_without_llm():
    def fake_client(messages):
        raise AssertionError("agent profile answer should not call LLM")

    result = generate_final_answer(
        FinalAnswerRequest(
            answer_mode="direct_answer",
            question="你是谁？你有什么功能？",
        ),
        client=fake_client,
    )

    assert "我是 raster-map-agent" in result.final_answer
    assert "NDVI" in result.final_answer
    assert "NDWI" in result.final_answer
    assert "population" in result.final_answer
    assert "landtype" in result.final_answer
    assert "可运行示例" in result.final_answer


def test_generate_final_answer_agent_profile_supports_more_phrasings():
    def fake_client(messages):
        raise AssertionError("agent profile answer should not call LLM")

    for question in ("使用说明", "What can you do?"):
        result = generate_final_answer(
            FinalAnswerRequest(
                answer_mode="direct_answer",
                question=question,
            ),
            client=fake_client,
        )
        assert "我是 raster-map-agent" in result.final_answer


def test_generate_final_answer_metadata_summary_with_fake_client():
    def fake_client(messages):
        assert "workflow metadata" in messages[1]["content"]
        assert '"metadata_has_failure": false' in messages[1]["content"]
        assert "Chengdu, Sichuan, China" in messages[1]["content"]
        assert "preview.png" in messages[1]["content"]
        return """
        ```json
        {
          "final_answer": "已生成成都 NDVI 专题图，预览图为 preview.png。"
        }
        ```
        """

    result = generate_final_answer(
        FinalAnswerRequest(
            answer_mode="metadata_summary",
            user_query="生成成都 NDVI 图",
            metadata={
                "plan": {
                    "aoi_query": "Chengdu, Sichuan, China",
                    "index_name": "NDVI",
                },
                "render_preview": {
                    "preview_path": "data/run/output/preview.png",
                },
            },
        ),
        client=fake_client,
    )

    assert result.final_answer == "已生成成都 NDVI 专题图，预览图为 preview.png。"


def test_generate_final_answer_failure_metadata_prompt_with_fake_client():
    def fake_client(messages):
        assert '"metadata_has_failure": true' in messages[1]["content"]
        assert "失败阶段" in messages[1]["content"]
        assert "正常运行" in messages[1]["content"]
        assert "No scenes found" in messages[1]["content"]
        return '{"final_answer": "任务失败：未找到满足条件的影像。示例：生成成都 NDVI 图。"}'

    result = generate_final_answer(
        FinalAnswerRequest(
            answer_mode="metadata_summary",
            user_query="生成成都 NDVI 图",
            metadata={
                "status": "failed",
                "errors": ["No scenes found"],
            },
        ),
        client=fake_client,
    )

    assert "未找到满足条件的影像" in result.final_answer


def test_final_answer_request_requires_question_for_direct_answer():
    with pytest.raises(ValidationError):
        FinalAnswerRequest(answer_mode="direct_answer")


def test_final_answer_request_requires_user_query_for_metadata_summary():
    with pytest.raises(ValidationError):
        FinalAnswerRequest(answer_mode="metadata_summary")


def test_generate_final_answer_rejects_invalid_json():
    with pytest.raises(FinalAnswerError, match="LLM response is not valid JSON"):
        generate_final_answer(
            FinalAnswerRequest(
                answer_mode="direct_answer",
                question="什么是遥感？",
            ),
            client=lambda messages: "not json",
        )


def test_generate_final_answer_rejects_missing_final_answer():
    with pytest.raises(FinalAnswerError, match="missing final_answer"):
        generate_final_answer(
            FinalAnswerRequest(
                answer_mode="direct_answer",
                question="什么是遥感？",
            ),
            client=lambda messages: '{"answer": "hello"}',
        )
