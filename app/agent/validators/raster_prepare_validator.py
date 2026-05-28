from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas import AgentState

RasterPrepareValidationStatus = Literal["passed", "retryable", "failed"]


class RasterPrepareValidationResult(BaseModel):
    """raster_prepare 结果的结构化校验结论。

    validator 只负责判断当前数据准备结果是否可用，不直接修改参数、
    不重新调用下载工具。后续 node 可以根据 status 决定继续执行、
    调用 adjuster，或者终止 workflow。
    """

    target: str = "raster_prepare"
    status: RasterPrepareValidationStatus
    is_retryable: bool = False
    reasons: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @property
    def should_continue(self) -> bool:
        """是否可以进入下一个业务步骤。"""

        return self.status == "passed"

    @property
    def should_adjust(self) -> bool:
        """是否应该调用 adjuster 修改参数后重试。"""

        return self.status == "retryable"


def validate_raster_prepare_result(
    state: AgentState,
) -> RasterPrepareValidationResult:
    """检查 raster_prepare 输出是否满足后续计算要求。"""

    prepare_result = _as_dict(state.tool_results.get("raster_prepare"))
    if not prepare_result:
        return _failed(["missing_raster_prepare_result"])

    raster_product = _get_registry_raster_product(state)
    required_bands = (
        raster_product.get("required_bands")
        or prepare_result.get("required_bands")
        or state.plan.get("required_bands")
        or []
    )
    if not required_bands:
        return _failed(["missing_required_bands"])

    diagnostics = _as_dict(prepare_result.get("diagnostics"))
    if not diagnostics:
        return _failed(["missing_raster_prepare_diagnostics"])

    coverage_ratio = float(diagnostics.get("coverage_ratio", 0))
    min_coverage_ratio = float(diagnostics.get("min_coverage_ratio", 1))
    coverage_status = diagnostics.get("coverage_status")

    if coverage_status == "covered" or coverage_ratio >= min_coverage_ratio:
        band_paths = _as_dict(prepare_result.get("band_paths"))
        missing_bands = [band for band in required_bands if not band_paths.get(band)]
        if missing_bands:
            return _failed([f"missing_band_paths:{','.join(missing_bands)}"])

        return RasterPrepareValidationResult(
            status="passed",
            diagnostics=diagnostics,
        )

    reason = diagnostics.get("failure_reason") or "raster_prepare_not_acceptable"
    suggested_actions = list(diagnostics.get("suggested_actions", []))

    if diagnostics.get("is_retriable"):
        return RasterPrepareValidationResult(
            status="retryable",
            is_retryable=True,
            reasons=[reason],
            suggested_actions=suggested_actions,
            diagnostics=diagnostics,
        )

    return RasterPrepareValidationResult(
        status="failed",
        reasons=[reason],
        suggested_actions=suggested_actions,
        diagnostics=diagnostics,
    )


def build_raster_prepare_validation_update(
    result: RasterPrepareValidationResult,
) -> dict[str, Any]:
    """把校验结论转换成 LangGraph state update。"""

    update: dict[str, Any] = {
        "runtime": {
            "validators": {
                "raster_prepare": result.model_dump(mode="json"),
            }
        }
    }

    if result.status == "passed":
        update["status"] = "raster_prepare_validated"
    elif result.status == "retryable":
        update["status"] = "raster_prepare_retryable"
    else:
        update["status"] = "failed"
        update["errors"] = result.reasons

    return update


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    return {}


def _get_registry_raster_product(state: AgentState) -> dict[str, Any]:
    registry = _as_dict(state.runtime.get("registry"))
    raster_product = _as_dict(registry.get("raster_product"))
    if raster_product:
        return raster_product

    return _as_dict(state.metadata.get("registry"))


def _failed(reasons: list[str]) -> RasterPrepareValidationResult:
    return RasterPrepareValidationResult(
        status="failed",
        reasons=reasons,
    )
