try:
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:
    END = START = None
    StateGraph = None

from app.agent.nodes import (
    answer_node,
    compiler_node,
    has_next_tool_call,
    planner_node,
    registry_node,
    tool_adjuster_node,
    tool_executor_node,
    tool_validator_node,
)
from app.schemas.state import AgentState, merge_dicts
from app.workflows.templates import (
    DIRECT_ANSWER_ROUTE,
    RASTER_PRODUCT_GENERATE_ROUTE,
)
from app.workflows.tool_rules import has_tool_rule


def route_after_planning(state: AgentState) -> str:
    """planner 后的路由。

    direct_answer 不需要 registry，直接进入 compiler。
    raster_product_generate 需要先进入 registry，解析指数配置。
    """
    if state.status == "failed":
        return "failed"

    if state.plan.get("route") == DIRECT_ANSWER_ROUTE:
        return DIRECT_ANSWER_ROUTE

    return RASTER_PRODUCT_GENERATE_ROUTE


def route_after_registry(state: AgentState) -> str:
    """registry 后的路由。"""
    if state.status == "failed":
        return "failed"

    return "ok"


def route_after_compilation(state: AgentState) -> str:
    """compiler 后的路由。"""
    if state.status == "failed":
        return "failed"

    if not state.tool_calls:
        return "failed"

    return "ok"


def route_after_tool_execution(state: AgentState) -> str:
    """单步 tool 执行后的路由。

    executor 每次只执行一个 tool_call。执行完成后，根据刚刚执行的
    tool_call 是否存在 tool rule，决定是否进入 validator。

    路由顺序：
    1. workflow 已失败 -> answer
    2. 刚执行的 tool_call 有 rule -> validator
    3. 还有下一个 tool_call -> executor
    4. 没有更多 tool_call -> answer
    """
    if state.status == "failed":
        return "failed"

    last_tool_call_id = _get_last_tool_call_id(state)
    if has_tool_rule(last_tool_call_id):
        return "validate"

    if has_next_tool_call(state):
        return "continue"

    return "done"


def route_after_validation(state: AgentState) -> str:
    """validator 后的路由。

    validator 只验证刚刚执行完成的 tool_call。当前主要是 raster_prepare。

    预期 validator 状态：
    - passed: 继续执行后续 tool_call
    - retryable: 进入 adjuster
    - failed: 进入 answer
    """
    if state.status == "failed":
        return "failed"

    last_tool_call_id = _get_last_tool_call_id(state)
    validation_status = _get_validation_status(state, last_tool_call_id)

    if validation_status == "passed":
        return "continue" if has_next_tool_call(state) else "done"

    if validation_status == "retryable":
        return "adjust"

    return "failed"


def route_after_adjustment(state: AgentState) -> str:
    """adjuster 后的路由。

    adjuster 成功时会：
    - 修改 tool_calls[last_tool_index].params
    - 设置 runtime.current_tool_index = last_tool_index

    因此 adjusted 后应回到 executor，重新执行刚刚被调整的 tool_call。
    """
    if state.status == "failed":
        return "failed"

    if state.status.endswith("_adjusted") or state.status == "tool_adjusted":
        return "adjusted"

    return "failed"


def build_workflow():
    """构建 LangGraph workflow。"""
    if StateGraph is None:
        return _LinearWorkflow()

    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("registry", registry_node)
    workflow.add_node("compiler", compiler_node)
    workflow.add_node("execute_tool", tool_executor_node)
    workflow.add_node("validate_tool", tool_validator_node)
    workflow.add_node("adjust_tool", tool_adjuster_node)
    workflow.add_node("answer", answer_node)

    workflow.add_edge(START, "planner")

    workflow.add_conditional_edges(
        "planner",
        route_after_planning,
        {
            DIRECT_ANSWER_ROUTE: "compiler",
            RASTER_PRODUCT_GENERATE_ROUTE: "registry",
            "failed": "answer",
        },
    )

    workflow.add_conditional_edges(
        "registry",
        route_after_registry,
        {
            "ok": "compiler",
            "failed": "answer",
        },
    )

    workflow.add_conditional_edges(
        "compiler",
        route_after_compilation,
        {
            "ok": "execute_tool",
            "failed": "answer",
        },
    )

    workflow.add_conditional_edges(
        "execute_tool",
        route_after_tool_execution,
        {
            "validate": "validate_tool",
            "continue": "execute_tool",
            "done": "answer",
            "failed": "answer",
        },
    )

    workflow.add_conditional_edges(
        "validate_tool",
        route_after_validation,
        {
            "continue": "execute_tool",
            "adjust": "adjust_tool",
            "done": "answer",
            "failed": "answer",
        },
    )

    workflow.add_conditional_edges(
        "adjust_tool",
        route_after_adjustment,
        {
            "adjusted": "execute_tool",
            "failed": "answer",
        },
    )

    workflow.add_edge("answer", END)

    return workflow.compile()


class _LinearWorkflow:
    """缺少 LangGraph 时使用的轻量 fallback runner。

    该 runner 模拟新 workflow：
    planner -> registry/compiler -> 单步 executor -> validator/adjuster loop -> answer
    """

    max_steps: int = 50

    def invoke(self, state: AgentState) -> AgentState:
        state = _apply_update(state, planner_node(state))

        planning_route = route_after_planning(state)
        if planning_route == "failed":
            return _apply_update(state, answer_node(state))

        if planning_route == RASTER_PRODUCT_GENERATE_ROUTE:
            state = _apply_update(state, registry_node(state))
            if route_after_registry(state) == "failed":
                return _apply_update(state, answer_node(state))

        state = _apply_update(state, compiler_node(state))
        if route_after_compilation(state) == "failed":
            return _apply_update(state, answer_node(state))

        steps = 0
        while steps < self.max_steps:
            steps += 1

            state = _apply_update(state, tool_executor_node(state))

            route = route_after_tool_execution(state)
            if route == "failed":
                return _apply_update(state, answer_node(state))

            if route == "done":
                return _apply_update(state, answer_node(state))

            if route == "continue":
                continue

            if route == "validate":
                state = _apply_update(state, tool_validator_node(state))
                validation_route = route_after_validation(state)

                if validation_route == "failed":
                    return _apply_update(state, answer_node(state))

                if validation_route == "done":
                    return _apply_update(state, answer_node(state))

                if validation_route == "continue":
                    continue

                if validation_route == "adjust":
                    state = _apply_update(state, tool_adjuster_node(state))
                    adjustment_route = route_after_adjustment(state)

                    if adjustment_route == "adjusted":
                        continue

                    return _apply_update(state, answer_node(state))

        state = _apply_update(
            state,
            {
                "status": "failed",
                "errors": [
                    f"Workflow exceeded max_steps={self.max_steps}. "
                    "Possible tool execution loop."
                ],
            },
        )
        return _apply_update(state, answer_node(state))


def _apply_update(state: AgentState, update: dict) -> AgentState:
    """把 node update 合并回 AgentState。

    这里模拟 LangGraph reducer 行为，用于 LinearWorkflow fallback。
    """
    data = state.model_dump(mode="json")

    for key, value in update.items():
        if key in {
            "plan",
            "workspace",
            "tool_results",
            "runtime",
            "metadata",
        }:
            data[key] = merge_dicts(data.get(key, {}), value)
        elif key == "tool_calls":
            data[key] = value
        elif key in {"errors", "warnings"}:
            data[key] = data.get(key, []) + value
        else:
            data[key] = value

    return AgentState.model_validate(data)


def _get_last_tool_call_id(state: AgentState) -> str | None:
    """读取最近一次执行完成的 tool_call 短 id。"""
    value = state.runtime.get("last_tool_call_id")
    if isinstance(value, str) and value.strip():
        return value

    return None


def _get_validation_status(
    state: AgentState,
    tool_call_id: str | None,
) -> str | None:
    """读取最近一次 validator 状态。

    优先读取 validators[tool_call_id]，兼容 validators.latest。
    """
    validators = state.runtime.get("validators", {})
    if not isinstance(validators, dict):
        return None

    validation = None

    if tool_call_id:
        validation = validators.get(tool_call_id)

    if not isinstance(validation, dict):
        validation = validators.get("latest")

    if not isinstance(validation, dict):
        return None

    status = validation.get("status")
    if isinstance(status, str):
        return status

    return None


WORKFLOW = build_workflow()


def run_workflow(user_query: str) -> AgentState:
    result = WORKFLOW.invoke(AgentState(user_query=user_query))
    return AgentState.model_validate(result)
