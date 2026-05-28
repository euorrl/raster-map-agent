from app.tools.index_calculation.schemas import (
    IndexCalculationError,
    IndexCalculationRequest,
    IndexCalculationResult,
)

__all__ = [
    "IndexCalculationError",
    "IndexCalculationRequest",
    "IndexCalculationResult",
    "calculate_raster_index",
]


def calculate_raster_index(
    request: IndexCalculationRequest,
) -> IndexCalculationResult:
    """Lazy wrapper for the rasterio-backed index calculation tool."""

    from app.tools.index_calculation.calculation import (
        calculate_raster_index as _calculate_raster_index,
    )

    return _calculate_raster_index(request)
