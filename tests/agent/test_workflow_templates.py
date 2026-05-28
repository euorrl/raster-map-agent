import pytest

from app.agent.workflow_templates import (
    DIRECT_ANSWER_ROUTE,
    RASTER_PRODUCT_GENERATE_ROUTE,
    WORKFLOW_TEMPLATES,
    get_workflow_route_answer_modes,
    get_workflow_template,
    get_workflow_template_routes,
)


def test_raster_product_generate_template_declares_full_tool_sequence():
    template = get_workflow_template(RASTER_PRODUCT_GENERATE_ROUTE)

    assert template.route == RASTER_PRODUCT_GENERATE_ROUTE
    assert template.answer_mode == "metadata_summary"
    assert template.tool_names == (
        "workspace.create_workspace",
        "raster_prepare.prepare_raster_inputs",
        "index_calculation.calculate_raster_index",
        "render_preview.render_index_preview",
        "metadata.export_metadata",
        "answer.generate_final_answer",
    )


def test_direct_answer_template_uses_only_answer_tool():
    template = get_workflow_template(DIRECT_ANSWER_ROUTE)

    assert template.route == DIRECT_ANSWER_ROUTE
    assert template.answer_mode == "direct_answer"
    assert template.tool_names == ("answer.generate_final_answer",)


def test_template_routes_and_answer_modes_are_registry_backed():
    assert get_workflow_template_routes() == sorted(WORKFLOW_TEMPLATES)
    assert get_workflow_route_answer_modes() == {
        RASTER_PRODUCT_GENERATE_ROUTE: "metadata_summary",
        DIRECT_ANSWER_ROUTE: "direct_answer",
    }


def test_get_workflow_template_rejects_unknown_route():
    with pytest.raises(ValueError, match="Unsupported workflow route"):
        get_workflow_template("unknown")
