from app.agent.nodes import answer_node
from app.schemas import AgentState
from app.workflows.v1_workflow import route_after_planning, run_v1_workflow


def test_v1_workflow_completes_mock_ndvi_request():
    # 验证 V1 mock workflow 能完整跑通一个 NDVI 请求。
    state = run_v1_workflow("Generate an NDVI vegetation map for Milan.")

    assert state.status == "completed"
    assert state.plan["index_name"] == "NDVI"
    assert state.plan["required_bands"] == ["B04", "B08"]
    assert state.tool_results["render_preview"]["preview_path"]
    assert state.final_answer
    assert state.metadata["plan"]["aoi_query"] == "Milan"
    assert state.warnings == [
        "Using mock AOI bounding box for Milan.",
        "Using mock Sentinel-2 band paths.",
    ]


def test_route_after_planning_sends_direct_answer_to_answer_node():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"response_mode": "direct_answer"},
        status="planned",
    )

    assert route_after_planning(state) == "direct_answer"


def test_answer_node_handles_direct_answer_mode():
    state = AgentState(
        user_query="What is remote sensing?",
        plan={"response_mode": "direct_answer"},
        status="planned",
    )

    update = answer_node(state)

    assert update["status"] == "completed"
    assert update["final_answer"] == "Mock direct answer for: What is remote sensing?"
