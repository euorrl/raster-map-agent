try:
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:
    END = START = None
    StateGraph = None

from app.agent.nodes import (
    answer_node,
    planner_node,
    product_generation_node,
    raster_prepare_node,
    raster_prepare_validator_node,
    registry_node,
    workspace_node,
)
from app.schemas.state import AgentState, merge_dicts
from app.workflows.templates import (
    DIRECT_ANSWER_ROUTE,
    RASTER_PRODUCT_GENERATE_ROUTE,
)


def route_after_planning(state: AgentState) -> str:
    if state.status == "failed":
        return "failed"
    if state.plan.get("route") == DIRECT_ANSWER_ROUTE:
        return DIRECT_ANSWER_ROUTE
    return RASTER_PRODUCT_GENERATE_ROUTE


def route_after_raster_prepare_validation(state: AgentState) -> str:
    if state.status == "raster_prepare_validated":
        return "prepared"
    return "failed"


def build_workflow():
    if StateGraph is None:
        return _LinearWorkflow()

    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("registry", registry_node)
    workflow.add_node("workspace", workspace_node)
    workflow.add_node("raster_prepare", raster_prepare_node)
    workflow.add_node("raster_prepare_validator", raster_prepare_validator_node)
    workflow.add_node("product_generation", product_generation_node)
    workflow.add_node("answer", answer_node)

    workflow.add_edge(START, "planner")
    workflow.add_conditional_edges(
        "planner",
        route_after_planning,
        {
            DIRECT_ANSWER_ROUTE: "answer",
            "failed": "answer",
            RASTER_PRODUCT_GENERATE_ROUTE: "registry",
        },
    )
    workflow.add_edge("registry", "workspace")
    workflow.add_edge("workspace", "raster_prepare")
    workflow.add_edge("raster_prepare", "raster_prepare_validator")
    workflow.add_conditional_edges(
        "raster_prepare_validator",
        route_after_raster_prepare_validation,
        {
            "failed": "answer",
            "prepared": "product_generation",
        },
    )
    workflow.add_edge("product_generation", "answer")
    workflow.add_edge("answer", END)

    return workflow.compile()


class _LinearWorkflow:
    """Small fallback runner used when LangGraph is not installed."""

    def invoke(self, state: AgentState) -> AgentState:
        state = _apply_update(state, planner_node(state))
        if route_after_planning(state) == DIRECT_ANSWER_ROUTE:
            return _apply_update(state, answer_node(state))
        if state.status == "failed":
            return _apply_update(state, answer_node(state))

        state = _apply_update(state, registry_node(state))
        state = _apply_update(state, workspace_node(state))
        state = _apply_update(state, raster_prepare_node(state))
        state = _apply_update(state, raster_prepare_validator_node(state))
        if route_after_raster_prepare_validation(state) == "prepared":
            state = _apply_update(state, product_generation_node(state))

        return _apply_update(state, answer_node(state))


def _apply_update(state: AgentState, update: dict) -> AgentState:
    data = state.model_dump(mode="json")
    for key, value in update.items():
        if key in {
            "plan",
            "workspace",
            "tool_results",
            "runtime",
        }:
            data[key] = merge_dicts(data.get(key, {}), value)
        elif key in {"errors", "warnings"}:
            data[key] = data.get(key, []) + value
        else:
            data[key] = value

    return AgentState.model_validate(data)


WORKFLOW = build_workflow()


def run_workflow(user_query: str) -> AgentState:
    result = WORKFLOW.invoke(AgentState(user_query=user_query))
    return AgentState.model_validate(result)
