from typing import Any

from app.agent.planners import build_agent_plan, build_agent_plan_update
from app.registry import resolve_raster_product_config
from app.schemas import AgentState
from app.workflows.compiler import build_tool_calls_update
from app.workflows.executor import execute_current_tool_call
from app.workflows.tool_rules import (
    build_retry_exhausted_update,
    can_retry_tool,
    get_tool_rule,
    has_tool_rule,
)


def planner_node(state: AgentState) -> dict[str, Any]:
    """根据用户输入生成受控 workflow plan。"""
    result = build_agent_plan(state.user_query)
    return build_agent_plan_update(result)


def registry_node(state: AgentState) -> dict[str, Any]:
    """解析栅格产品配置，并写入 runtime.registry。

    该节点只负责把 plan 中的指数名称和数据源解析成稳定的产品配置，
    例如 required_bands、band_roles、index_formula、render_config 等。

    注意：
    - 该节点不写 metadata。
    - 最终 metadata 由 metadata.export_metadata tool 统一生成。
    """
    try:
        product_config = resolve_raster_product_config(
            state.plan.get("index_name", "NDVI"),
            state.plan.get("data_source", "sentinel2"),
        )
    except Exception as error:
        return {
            "errors": [f"Raster product registry resolution failed: {error}"],
            "status": "failed",
        }

    return {
        "runtime": {
            "registry": {
                "raster_product": product_config.model_dump(mode="json"),
            }
        }
    }


def compiler_node(state: AgentState) -> dict[str, Any]:
    """将 plan 和 registry 上下文编译成线性的 tool_calls。

    compiler 只负责编译工具调用列表，不执行任何工具。

    典型输出包括：
    - state.tool_calls
    - runtime.current_tool_index
    - runtime.compiler
    """
    try:
        return build_tool_calls_update(state)
    except Exception as error:
        return {
            "errors": [f"Tool call compilation failed: {error}"],
            "status": "failed",
        }


def has_next_tool_call(state: AgentState) -> bool:
    """判断当前是否还有待执行的 tool_call。

    runtime.current_tool_index 指向下一次 executor 应该执行的 tool_call。
    如果 current_tool_index 小于 tool_calls 长度，说明还有工具需要继续执行。
    """
    try:
        current_index = int(state.runtime.get("current_tool_index", 0))
    except (TypeError, ValueError):
        return False

    if not isinstance(state.tool_calls, list):
        return False

    return current_index < len(state.tool_calls)


def tool_executor_node(state: AgentState) -> dict[str, Any]:
    """单步执行当前 tool_call。

    该节点只执行 runtime.current_tool_index 指向的一个 tool_call。

    注意：
    - 不会一次性执行完整 tool_calls 列表。
    - 不负责调用 validator。
    - 不负责调用 adjuster。
    - 不直接从 plan 拼工具参数。
    - 具体参数来自 tool_call.params。
    - tool_call.params 中的 $state.xxx 引用由 executor 解析。
    """
    try:
        next_state = execute_current_tool_call(state)
    except Exception as error:
        return {
            "errors": [f"Tool execution failed: {error}"],
            "status": "failed",
        }

    return next_state.model_dump(mode="json")


def tool_validator_node(state: AgentState) -> dict[str, Any]:
    """验证刚刚执行完成的 tool_call。

    该节点通过 runtime.last_tool_call_id 找到上一个执行完成的 tool_call，
    然后根据 tool_rules 分发到对应 validator。

    注意：
    - tool_rules 使用的是 tool_call.id，也就是短 id，例如 raster_prepare。
    - 不使用 tool_call.tool_name，例如 raster_prepare.prepare_raster_inputs。
    - validator 只负责判断结果是否 passed / retryable / failed。
    - validator 不修改 tool_call 参数。
    - validator 不执行工具。
    - validator 不写 metadata。
    """
    last_tool_call_id = _get_last_tool_call_id(state)
    if not has_tool_rule(last_tool_call_id):
        return {
            "errors": ["Missing or unsupported tool rule for last tool call."],
            "status": "failed",
        }

    rule = get_tool_rule(last_tool_call_id)
    try:
        validation_result = rule.validator(state)
        return rule.validation_update_builder(validation_result)
    except Exception as error:
        return {
            "errors": [
                f"Tool validation failed for {last_tool_call_id}: {error}",
            ],
            "status": "failed",
        }


def tool_adjuster_node(state: AgentState) -> dict[str, Any]:
    """对 retryable 的 tool_call 执行参数调整。

    该节点通过 runtime.last_tool_call_id 找到刚刚验证失败但可调整的 tool_call，
    然后根据 tool_rules 分发到对应 adjuster。

    adjuster 的职责是：
    - 修改 tool_calls[last_tool_index].params。
    - 追加 runtime.adjustments。
    - 更新 runtime.retry_counts。
    - 将 runtime.current_tool_index 拉回 last_tool_index。
    - 让下一轮 executor 重新执行被调整过的 tool_call。

    注意：
    - adjuster 不修改 state.plan。
    - adjuster 不写 metadata。
    - adjuster 不执行工具。
    """
    last_tool_call_id = _get_last_tool_call_id(state)
    if not has_tool_rule(last_tool_call_id):
        return {
            "errors": ["Missing or unsupported tool rule for last tool call."],
            "status": "failed",
        }

    if not can_retry_tool(state, last_tool_call_id):
        return build_retry_exhausted_update(state, last_tool_call_id)

    rule = get_tool_rule(last_tool_call_id)
    try:
        adjustment_result = rule.adjuster(state)
        return rule.adjustment_update_builder(state, adjustment_result)
    except Exception as error:
        return {
            "errors": [
                f"Tool adjustment failed for {last_tool_call_id}: {error}",
            ],
            "status": "failed",
        }


def answer_node(state: AgentState) -> dict[str, Any]:
    """workflow 兜底终止节点。

    在新的 tool-call workflow 中，正常情况下最终回答由
    answer.generate_final_answer tool 生成。

    也就是说，answer tool 会作为最后一个 tool_call 被 executor 执行，
    并写入 state.final_answer。

    该节点只负责兜底：
    - 如果 final_answer 已存在，直接结束。
    - 如果 workflow 已失败，生成简单失败回答。
    - 如果没有 final_answer 但 workflow 未失败，生成简单兜底回答。
    """
    if state.final_answer is not None:
        return {
            "final_answer": state.final_answer,
            "status": state.status or "completed",
        }

    if state.status == "failed":
        error_text = "; ".join(state.errors) or "Unknown workflow error."
        return {
            "final_answer": f"Workflow failed: {error_text}",
            "status": "failed",
        }

    if state.plan.get("answer_mode") == "direct_answer":
        return {
            "final_answer": (
                f"Unable to generate a direct answer for: {state.user_query}"
            ),
            "status": "completed",
        }

    return {
        "final_answer": (
            f"Workflow completed for {state.plan.get('index_name')} "
            f"over {state.plan.get('aoi_query')}, "
            "but no final answer was generated."
        ),
        "status": "completed",
    }


def _get_last_tool_call_id(state: AgentState) -> str | None:
    """读取最近一次执行完成的 tool_call 短 id。"""
    value = state.runtime.get("last_tool_call_id")
    if isinstance(value, str) and value.strip():
        return value

    return None
