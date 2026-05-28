from app.agent.planners import build_agent_plan, build_agent_plan_update


def test_build_agent_plan_with_fake_client():
    def fake_client(messages):
        assert messages[0]["role"] == "system"
        assert "supported_indexes" in messages[1]["content"]
        assert "registered_options" in messages[1]["content"]
        assert "workflow_routes" in messages[1]["content"]
        assert "answer_modes" in messages[1]["content"]
        assert "不要默认选择 NDVI" in messages[1]["content"]
        assert "不要输出 tool_calls" in messages[1]["content"]
        assert "direct_answer" in messages[1]["content"]
        return """
        {
          "plan": {
            "route": "raster_product_generate",
            "answer_mode": "metadata_summary",
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "ndvi",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 20
          },
          "rationale": "User asks for an NDVI map of Chengdu."
        }
        """

    result = build_agent_plan("Calculate Chengdu NDVI", client=fake_client)
    update = build_agent_plan_update(result)

    assert result.status == "planned"
    assert result.plan == {
        "route": "raster_product_generate",
        "answer_mode": "metadata_summary",
        "aoi_query": "Chengdu, Sichuan, China",
        "index_name": "NDVI",
        "start_date": "2024-06-01",
        "end_date": "2024-08-31",
        "max_cloud_cover": 20,
    }
    assert result.rationale == "User asks for an NDVI map of Chengdu."
    assert update["status"] == "planned"
    assert update["plan"]["index_name"] == "NDVI"
    assert "metadata" not in update
    assert update["runtime"]["planners"]["global"]["status"] == "planned"
    assert "tool_calls" not in update
    assert "tool_plan" not in update["runtime"]


def test_build_agent_plan_accepts_nested_plan_object():
    result = build_agent_plan(
        "Analyze Wuhan water",
        client=lambda messages: """
        {
          "plan": {
            "route": "raster_product_generate",
            "answer_mode": "metadata_summary",
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
    assert result.rationale == "NDWI matches water analysis."


def test_build_agent_plan_direct_answer_skips_raster_fields():
    result = build_agent_plan(
        "What is remote sensing?",
        client=lambda messages: """
        {
          "plan": {
            "route": "direct_answer",
            "answer_mode": "direct_answer",
            "aoi_query": "Ignored",
            "index_name": "NDVI"
          },
          "rationale": "The user asks a general question."
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan == {
        "route": "direct_answer",
        "answer_mode": "direct_answer",
    }
    assert result.warnings == [
        "Ignored unsupported planner fields: aoi_query, index_name."
    ]


def test_build_agent_plan_direct_answer_route_defaults_answer_mode():
    result = build_agent_plan(
        "What is remote sensing?",
        client=lambda messages: """
        {
          "plan": {
            "route": "direct_answer"
          },
          "rationale": "The user asks a general question."
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan == {
        "route": "direct_answer",
        "answer_mode": "direct_answer",
    }


def test_build_agent_plan_accepts_legacy_response_mode():
    result = build_agent_plan(
        "What is remote sensing?",
        client=lambda messages: """
        {
          "plan": {
            "response_mode": "direct_answer"
          }
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan == {
        "route": "direct_answer",
        "answer_mode": "direct_answer",
    }


def test_build_agent_plan_caps_cloud_cover_and_ignores_internal_fields():
    result = build_agent_plan(
        "Calculate Chengdu NDVI",
        client=lambda messages: """
        {
          "plan": {
            "route": "raster_product_generate",
            "answer_mode": "metadata_summary",
            "aoi_query": "Chengdu, Sichuan, China",
            "index_name": "NDVI",
            "data_source": "sentinel2",
            "start_date": "2024-06-01",
            "end_date": "2024-08-31",
            "max_cloud_cover": 80,
            "scene_limit": 100,
            "max_selected_scenes": 30
          }
        }
        """,
    )

    assert result.status == "planned"
    assert result.plan["max_cloud_cover"] == 30
    assert result.warnings == [
        (
            "Ignored unsupported planner fields: data_source, "
            "max_selected_scenes, scene_limit."
        )
    ]


def test_build_agent_plan_rejects_unsupported_index():
    result = build_agent_plan(
        "Calculate urban heat island",
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
    result = build_agent_plan("Calculate Chengdu NDVI", client=lambda messages: "x")

    assert result.status == "failed"
    assert result.error == "LLM response is not valid JSON."


def test_build_agent_plan_rejects_reversed_dates():
    result = build_agent_plan(
        "Calculate Chengdu NDVI",
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
