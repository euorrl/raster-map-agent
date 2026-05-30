from __future__ import annotations

from types import SimpleNamespace

from app.agent import nodes
from app.schemas import AgentState
from app.workflows.tool_rules import TOOL_RULES_BY_CALL_ID


def test_answer_node_prefers_final_answer() -> None:
    state = AgentState(
        user_query="What is the index?",
        plan={"answer_mode": "direct_answer"},
        final_answer="Existing final answer",
        status="completed",
    )

    result = nodes.answer_node(state)

    assert result["final_answer"] == "Existing final answer"
    assert result["status"] == "completed"


def test_compiler_node_sets_current_tool_index() -> None:
    state = AgentState(
        user_query="Prepare raster",
        plan={
            "index_name": "NDVI",
            "aoi_query": "Test AOI",
            "start_date": "2024-01-01",
            "end_date": "2024-01-05",
            "answer_mode": "final_answer",
        },
        runtime={
            "registry": {
                "raster_product": {
                    "data_source": "sentinel2",
                    "band_roles": {"red": "B4", "green": "B3", "nir": "B8"},
                    "index_formula": "(nir - red)/(nir + red)",
                }
            }
        },
    )
    update = nodes.compiler_node(state)

    assert update["runtime"]["current_tool_index"] == 0
    assert isinstance(update["tool_calls"], list)


def test_tool_executor_node_invokes_executor(monkeypatch) -> None:
    def fake_execute(state: AgentState) -> AgentState:
        next_state = AgentState.model_validate(state.model_dump(mode="json"))
        next_state.runtime["last_tool_call_id"] = "fake_tool"
        return next_state

    monkeypatch.setattr(nodes, "execute_current_tool_call", fake_execute)
    state = AgentState(
        user_query="Run tool",
        tool_calls=[{"id": "fake_tool", "tool_name": "test_tool", "params": {}}],
        runtime={"current_tool_index": 0},
    )

    update = nodes.tool_executor_node(state)

    assert update["runtime"]["last_tool_call_id"] == "fake_tool"


def test_tool_validator_node_uses_rule_validator(monkeypatch) -> None:
    fake_rule = SimpleNamespace(
        validator=lambda state: {"status": "ok"},
        validation_update_builder=lambda result: {"status": result["status"]},
    )

    monkeypatch.setattr(nodes, "has_tool_rule", lambda tool_call_id: True)
    monkeypatch.setattr(nodes, "get_tool_rule", lambda tool_call_id: fake_rule)

    state = AgentState(
        user_query="Validate tool",
        runtime={"last_tool_call_id": "any_tool"},
    )

    update = nodes.tool_validator_node(state)

    assert update == {"status": "ok"}


def test_tool_adjuster_node_invokes_adjuster_when_retryable(monkeypatch) -> None:
    fake_rule = SimpleNamespace(
        adjuster=lambda state: {"retry": True},
        adjustment_update_builder=lambda state, result: {
            "status": "adjusted",
            "runtime": {"adjustments": {state.runtime["last_tool_call_id"]: result}},
        },
    )

    monkeypatch.setattr(nodes, "has_tool_rule", lambda tool_call_id: True)
    monkeypatch.setattr(nodes, "can_retry_tool", lambda state, tool_call_id: True)
    monkeypatch.setattr(nodes, "get_tool_rule", lambda tool_call_id: fake_rule)

    state = AgentState(
        user_query="Adjust tool",
        runtime={"last_tool_call_id": "any_tool"},
    )

    update = nodes.tool_adjuster_node(state)

    assert update["status"] == "adjusted"
    assert update["runtime"]["adjustments"]["any_tool"]["retry"] is True


def test_tool_adjuster_node_returns_retry_exhausted_when_no_retry() -> None:
    tool_call_id = next(iter(TOOL_RULES_BY_CALL_ID))
    state = AgentState(
        user_query="No retry",
        runtime={
            "last_tool_call_id": tool_call_id,
            "validators": {tool_call_id: {"status": "retryable"}},
            "retry_counts": {
                tool_call_id: TOOL_RULES_BY_CALL_ID[tool_call_id].max_retries
            },
        },
    )

    update = nodes.tool_adjuster_node(state)

    assert update["status"] == "failed"
    assert "retry limit" in update["errors"][0]
