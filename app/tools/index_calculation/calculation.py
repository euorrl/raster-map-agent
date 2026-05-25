"""栅格指数计算工具。"""

import ast
from pathlib import Path

import numpy as np
import rasterio

from app.tools.index_calculation.schemas import (
    IndexCalculationError,
    IndexCalculationRequest,
    IndexCalculationResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

OUTPUT_NODATA = -9999.0


def calculate_raster_index(request: IndexCalculationRequest) -> IndexCalculationResult:
    """根据裁剪后的 band GeoTIFF 计算指数，并输出单个指数 GeoTIFF。"""

    logger.info(
        "Calculating raster index index=%s output_path=%s",
        request.index_name,
        request.output_path,
    )

    role_arrays, valid_mask, profile = _load_role_arrays(request)
    index_data = _evaluate_formula(request.index_formula, role_arrays)
    index_data = np.asarray(index_data, dtype="float32")

    if index_data.shape != valid_mask.shape:
        raise IndexCalculationError(
            f"Formula result shape does not match input bands: {index_data.shape}"
        )

    valid_mask = valid_mask & np.isfinite(index_data)
    output_data = np.full(index_data.shape, OUTPUT_NODATA, dtype="float32")
    output_data[valid_mask] = index_data[valid_mask]

    profile.update(
        dtype="float32",
        count=1,
        nodata=OUTPUT_NODATA,
    )

    request.output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(request.output_path, "w", **profile) as destination:
        destination.write(output_data, 1)

    logger.info("Saved raster index path=%s", request.output_path)
    return IndexCalculationResult(index_tif_path=str(request.output_path))


def _load_role_arrays(
    request: IndexCalculationRequest,
) -> tuple[dict[str, np.ndarray], np.ndarray, dict]:
    """读取公式角色对应的 band，并构建统一的有效像素 mask。"""

    role_arrays = {}
    valid_mask = None
    reference_shape = None
    reference_transform = None
    reference_crs = None
    reference_profile = None

    for role, band in request.band_roles.items():
        band_path = request.band_paths[band]
        _ensure_file_exists(band_path, band)

        with rasterio.open(band_path) as source:
            data = source.read(1).astype("float32")
            if reference_shape is None:
                reference_shape = data.shape
                reference_transform = source.transform
                reference_crs = source.crs
                reference_profile = source.profile.copy()
            else:
                _ensure_aligned(
                    path=band_path,
                    shape=data.shape,
                    transform=source.transform,
                    crs=source.crs,
                    reference_shape=reference_shape,
                    reference_transform=reference_transform,
                    reference_crs=reference_crs,
                )

            band_valid_mask = np.isfinite(data)
            if source.nodata is not None:
                band_valid_mask = band_valid_mask & (data != float(source.nodata))

        role_arrays[role] = data
        valid_mask = (
            band_valid_mask if valid_mask is None else valid_mask & band_valid_mask
        )

    if not role_arrays or valid_mask is None or reference_profile is None:
        raise IndexCalculationError("No input bands were loaded")

    return role_arrays, valid_mask, reference_profile


def _ensure_file_exists(path: Path, band: str) -> None:
    """确认输入 band 文件存在。"""

    if not path.exists():
        raise IndexCalculationError(f"Input band {band} does not exist: {path}")


def _ensure_aligned(
    path: Path,
    shape: tuple[int, int],
    transform,
    crs,
    reference_shape: tuple[int, int],
    reference_transform,
    reference_crs,
) -> None:
    """确认所有输入 band 已经在同一网格上。"""

    if (
        shape != reference_shape
        or transform != reference_transform
        or crs != reference_crs
    ):
        raise IndexCalculationError(f"Input band is not aligned: {path}")


def _evaluate_formula(
    formula: str,
    variables: dict[str, np.ndarray],
) -> np.ndarray:
    """用受限 AST 执行指数公式，避免直接 eval 任意代码。"""

    try:
        expression = ast.parse(formula, mode="eval")
    except SyntaxError as error:
        raise IndexCalculationError(f"Invalid index formula: {formula}") from error

    with np.errstate(divide="ignore", invalid="ignore"):
        return _evaluate_ast_node(expression.body, variables)


def _evaluate_ast_node(node: ast.AST, variables: dict[str, np.ndarray]):
    """递归执行受限公式节点。"""

    if isinstance(node, ast.Name):
        try:
            return variables[node.id]
        except KeyError as error:
            raise IndexCalculationError(
                f"Formula references unknown band role: {node.id}"
            ) from error

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_ast_node(node.operand, variables)
        return value if isinstance(node.op, ast.UAdd) else -value

    if isinstance(node, ast.BinOp):
        left = _evaluate_ast_node(node.left, variables)
        right = _evaluate_ast_node(node.right, variables)
        return _apply_operator(node.op, left, right)

    raise IndexCalculationError(
        f"Unsupported expression in index formula: {ast.dump(node)}"
    )


def _apply_operator(operator: ast.operator, left, right):
    """执行公式支持的四则运算。"""

    if isinstance(operator, ast.Add):
        return left + right
    if isinstance(operator, ast.Sub):
        return left - right
    if isinstance(operator, ast.Mult):
        return left * right
    if isinstance(operator, ast.Div):
        return left / right

    raise IndexCalculationError(
        f"Unsupported operator in index formula: {operator.__class__.__name__}"
    )
