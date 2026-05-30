from app.tools.render_preview.schemas import (
    RenderPreviewError,
    RenderPreviewRequest,
    RenderPreviewResult,
)

__all__ = [
    "RenderPreviewError",
    "RenderPreviewRequest",
    "RenderPreviewResult",
    "render_index_preview",
]


def render_index_preview(request: RenderPreviewRequest) -> RenderPreviewResult:
    """Lazy wrapper for the rasterio-backed preview rendering tool."""

    from app.tools.render_preview.render import (
        render_index_preview as _render_index_preview,
    )

    return _render_index_preview(request)
