from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    answer_node,
    planner_node,
    product_generation_node,
    raster_prepare_node,
    raster_prepare_validator_node,
    registry_node,
    workspace_node,
)
from app.schemas.state import AgentState


def route_after_planning(state: AgentState) -> str:
    if state.status == "failed":
        return "failed"
    if state.plan.get("response_mode") == "direct_answer":
        return "direct_answer"
    return "raster_workflow"


def route_after_raster_prepare_validation(state: AgentState) -> str:
    if state.status == "raster_prepared":
        return "prepared"
    return "failed"


def build_workflow():
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
            "direct_answer": "answer",
            "failed": "answer",
            "raster_workflow": "registry",
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


WORKFLOW = build_workflow()


def run_workflow(user_query: str) -> AgentState:
    result = WORKFLOW.invoke(AgentState(user_query=user_query))
    return AgentState.model_validate(result)
