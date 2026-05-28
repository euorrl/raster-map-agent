from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    answer_node,
    aoi_node,
    download_node,
    metadata_node,
    planner_node,
    process_node,
    registry_node,
    render_node,
    validator_node,
    workflow_router_node,
)
from app.schemas.state import AgentState


def route_after_planning(state: AgentState) -> str:
    if state.status == "failed":
        return "failed"
    if state.plan.get("response_mode") == "direct_answer":
        return "direct_answer"
    return "raster_workflow"


def route_after_validation(state: AgentState) -> str:
    if state.status == "validated":
        return "validated"
    return "failed"


def build_v1_workflow():
    workflow = StateGraph(AgentState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("registry", registry_node)
    workflow.add_node("workflow_router", workflow_router_node)
    workflow.add_node("aoi", aoi_node)
    workflow.add_node("download", download_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("process", process_node)
    workflow.add_node("render", render_node)
    workflow.add_node("metadata", metadata_node)
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
    workflow.add_edge("registry", "workflow_router")
    workflow.add_edge("workflow_router", "aoi")
    workflow.add_edge("aoi", "download")
    workflow.add_edge("download", "validator")
    workflow.add_conditional_edges(
        "validator",
        route_after_validation,
        {
            "failed": "answer",
            "validated": "process",
        },
    )
    workflow.add_edge("process", "render")
    workflow.add_edge("render", "metadata")
    workflow.add_edge("metadata", "answer")
    workflow.add_edge("answer", END)

    return workflow.compile()


V1_WORKFLOW = build_v1_workflow()


def run_v1_workflow(user_query: str) -> AgentState:
    result = V1_WORKFLOW.invoke(AgentState(user_query=user_query))
    return AgentState.model_validate(result)
