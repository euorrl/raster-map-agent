from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AnswerMode = Literal["metadata_summary", "direct_answer"]


class FinalAnswerError(RuntimeError):
    """最终回答生成失败时抛出的错误。"""


class FinalAnswerRequest(BaseModel):
    """最终回答生成请求。"""

    answer_mode: AnswerMode
    question: str | None = None
    user_query: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_answer_request(self):
        if self.answer_mode == "direct_answer":
            if not self.question or not self.question.strip():
                raise ValueError("question is required for direct_answer mode.")

        if self.answer_mode == "metadata_summary":
            if not self.user_query or not self.user_query.strip():
                raise ValueError("user_query is required for metadata_summary mode.")

        return self


class FinalAnswerResult(BaseModel):
    """最终回答生成结果。"""

    final_answer: str = Field(min_length=1)
