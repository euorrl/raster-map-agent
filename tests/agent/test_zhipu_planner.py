from app.agent.planners import build_agent_plan, build_agent_plan_update


def test_build_agent_plan_with_fake_client():
    def fake_client(messages):
        assert messages[0]["role"] == "system"
        assert "supported_indexes" in messages[1]["content"]
        assert "registered_options" in messages[1]["content"]
        assert "tool_contracts" in messages[1]["content"]
        assert "不要默认选择 NDVI" in messages[1]["content"]
        assert "日期推断优先级" in messages[1]["content"]
        assert (
            "workspace.create_workspace：创建本次任务工作目录" in messages[1]["content"]
        )
        assert "direct_answer" in messages[1]["content"]
        return """
        {
          "plan": {
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "ndvi",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 20
          },
          "tool_calls": [
            {"tool": "workspace.create_workspace", "params": {}},
            {"tool": "raster_prepare.prepare_raster_inputs", "params": {}},
            {"tool": "index_calculation.calculate_raster_index", "params": {}},
            {"tool": "render_preview.render_index_preview", "params": {}},
            {"tool": "metadata.export_metadata", "params": {}},
            {"tool": "answer.generate_final_answer", "params": {}}
          ],
          "rationale": "User asks for an NDVI map of Chengdu."
        }
        """

    result = build_agent_plan("计算成都 NDVI", client=fake_client)
    update = build_agent_plan_update(result)

    assert result.status == "planned"
    assert result.plan == {
        "response_mode": "raster_workflow",
        "aoi_query": "Chengdu, Sichuan, China",
        "index_name": "NDVI",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
    }
    assert [tool_call["tool"] for tool_call in result.tool_calls] == [
        "workspace.create_workspace",
        "raster_prepare.prepare_raster_inputs",
        "index_calculation.calculate_raster_index",
        "render_preview.render_index_preview",
        "metadata.export_metadata",
        "answer.generate_final_answer",
    ]
    assert result.tool_calls[1]["params"] == {
        "aoi_query": "Chengdu, Sichuan, China",
        "index_name": "NDVI",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
    }
    assert result.tool_calls[-1]["params"] == {
        "answer_mode": "metadata_summary",
        "user_query": "$state.user_query",
        "metadata": "$metadata",
    }
    assert result.tool_calls[4]["params"] == {
        "workspace_dir": "$workspace.workspace_dir",
        "metadata": "$metadata",
    }
    assert result.rationale == "User asks for an NDVI map of Chengdu."
    assert update["status"] == "planned"
    assert update["plan"]["index_name"] == "NDVI"
    assert update["metadata"]["plan"]["aoi_query"] == "Chengdu, Sichuan, China"
    assert update["runtime"]["planners"]["global"]["status"] == "planned"
    assert update["runtime"]["tool_plan"]["steps"][0]["tool"] == (
        "workspace.create_workspace"
    )


def test_build_agent_plan_accepts_nested_plan_object():
    result = build_agent_plan(
        "分析武汉水体",
        client=lambda messages: """
        {
          "plan": {
            "aoi_query": "Wuhan, Hubei, China",
            "index_name": "NDWI",
            "start_date": "2024-07-01",
            "end_date": "2024-09-01"
          },
          "rationale": "NDWI matches water analysis."
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan["index_name"] == "NDWI"
    assert result.plan["max_cloud_cover"] == 20
    assert result.tool_calls[0]["tool"] == "workspace.create_workspace"
    assert result.rationale == "NDWI matches water analysis."


def test_build_agent_plan_direct_answer_skips_raster_tools():
    result = build_agent_plan(
        "什么是遥感？",
        client=lambda messages: """
        {
          "plan": {
            "response_mode": "direct_answer"
          },
          "tool_calls": [
            {"tool": "workspace.create_workspace", "params": {}},
            {"tool": "answer.generate_final_answer", "params": {}}
          ],
          "rationale": "The user asks a general question, not for a raster workflow."
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan == {
        "response_mode": "direct_answer",
    }
    assert result.tool_calls == [
        {
            "step": 1,
            "tool": "answer.generate_final_answer",
            "params": {
                "answer_mode": "direct_answer",
                "question": "$state.user_query",
            },
        }
    ]


def test_build_agent_plan_caps_cloud_cover_and_ignores_internal_fields():
    result = build_agent_plan(
        "计算成都 NDVI",
        client=lambda messages: """
        {
          "plan": {
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "NDVI",
            "data_source": "sentinel2",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 80,
            "scene_limit": 100,
            "max_selected_scenes": 30
          },
          "tool_calls": [
            {"tool": "unknown.tool", "params": {}},
            {"tool": "raster_prepare.prepare_raster_inputs", "params": {}}
          ]
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan["max_cloud_cover"] == 30
    assert "Ignored unsupported planner fields" in result.warnings[0]
    assert "Ignored unsupported planner tool: unknown.tool." in result.warnings
    assert result.tool_calls == [
        {
            "step": 1,
            "tool": "raster_prepare.prepare_raster_inputs",
            "params": {
                "aoi_query": "Chengdu, Sichuan, China",
                "index_name": "NDVI",
                "start_date": "2024-06-01",
                "end_date": "2024-08-31",
                "max_cloud_cover": 30,
            },
        }
    ]


def test_build_agent_plan_rejects_unsupported_index():
    result = build_agent_plan(
        "计算城市热岛",
        client=lambda messages: """
        {
          "aoi_query": "Chengdu, Sichuan, China",
          "index_name": "LST",
          "start_date": "2024-06-01",
          "end_date": "2024-08-31"
        }
        """,
    )
    update = build_agent_plan_update(result)

    assert result.status == "failed"
    assert "Unsupported planner index_name" in result.error
    assert update["status"] == "failed"


def test_build_agent_plan_rejects_invalid_json():
    result = build_agent_plan("计算成都 NDVI", client=lambda messages: "not json")

    assert result.status == "failed"
    assert result.error == "LLM response is not valid JSON."


def test_build_agent_plan_rejects_reversed_dates():
    result = build_agent_plan(
        "计算成都 NDVI",
        client=lambda messages: """
        {
          "aoi_query": "Chengdu, Sichuan, China",
          "index_name": "NDVI",
          "start_date": "2024-09-01",
          "end_date": "2024-08-31"
        }
        """,
    )

    assert result.status == "failed"
    assert result.error == "Planner start_date cannot be later than end_date."


def test_build_agent_plan_uses_default_tool_calls_when_missing():
    result = build_agent_plan(
        "计算成都 NDVI",
        client=lambda messages: """
        {
          "aoi_query": "Chengdu, Sichuan, China",
          "index_name": "NDVI",
          "start_date": "2024-06-01",
          "end_date": "2024-08-31",
          "max_cloud_cover": 20
        }
        """,
    )

    assert result.status == "planned"
    assert result.warnings == [
        "Planner did not provide tool_calls; default V1 tool order was used."
    ]
    assert result.tool_calls[0]["tool"] == "workspace.create_workspace"
