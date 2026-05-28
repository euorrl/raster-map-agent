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


def test_generate_final_answer_metadata_summary_with_fake_client():
    def fake_client(messages):
        assert "workflow metadata" in messages[1]["content"]
        assert "Chengdu, Sichuan, China" in messages[1]["content"]
        assert "ndvi_preview.png" in messages[1]["content"]
        return """
        ```json
        {
          "final_answer": "已生成成都 NDVI 专题图，预览图为 ndvi_preview.png。"
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
                    "preview_path": "data/run/output/ndvi_preview.png",
                },
            },
        ),
        client=fake_client,
    )

    assert result.final_answer == "已生成成都 NDVI 专题图，预览图为 ndvi_preview.png。"


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
