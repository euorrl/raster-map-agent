from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AnswerMode = Literal["metadata_summary", "direct_answer"]


class FinalAnswerError(RuntimeError):
    """最终回答生成失败时抛出的错误。"""


class FinalAnswerRequest(BaseModel):
    """最终回答生成请求。

    answer_mode 是 answer tool 的直接控制参数：
    - metadata_summary: 根据 workflow metadata 总结真实执行结果；失败时输出
      更详细的诊断和正常运行示例。
    - direct_answer: 对普通问题、当前不支持的产品或 agent 能力介绍类问题
      直接回答。
    - question 和 user_query 是 answer tool 的输入参数，分别用于 direct_answer 和
      metadata_summary 两种模式。answer tool 会根据 answer_mode 选择使用哪个参数。
    - metadata 是 answer tool 的输入参数，包含 workflow 执行的详细上下文信息，
      供 answer tool 生成回答时参考。
    """

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
