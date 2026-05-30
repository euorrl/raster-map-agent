"""栅格指数计算工具。"""

import ast
from pathlib import Path
import shutil

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from app.tools.raster_prepare.schemas import CLIPPED_RASTER_DIRNAME
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
    _remove_clipped_raster_dir(request.workspace_dir)
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
                data = _align_to_reference_grid(
                    path=band_path,
                    data=data,
                    source_nodata=source.nodata,
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


def _align_to_reference_grid(
    path: Path,
    data: np.ndarray,
    source_nodata,
    shape: tuple[int, int],
    transform,
    crs,
    reference_shape: tuple[int, int],
    reference_transform,
    reference_crs,
) -> np.ndarray:
    """将输入 band 对齐到第一个 band 的网格。"""

    if (
        shape == reference_shape
        and transform == reference_transform
        and crs == reference_crs
    ):
        return data

    if crs is None or reference_crs is None:
        raise IndexCalculationError(
            f"Input band is not aligned and CRS is missing: {path}"
        )

    logger.info("Resampling input band to reference grid path=%s", path)
    destination = np.full(reference_shape, np.nan, dtype="float32")
    reproject(
        source=data,
        destination=destination,
        src_transform=transform,
        src_crs=crs,
        src_nodata=source_nodata,
        dst_transform=reference_transform,
        dst_crs=reference_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return destination


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


def _remove_clipped_raster_dir(workspace_dir: Path) -> None:
    """删除指数计算消费完成后的 clipped_raster 中间目录。"""

    resolved_workspace = workspace_dir.resolve()
    target_dir = (workspace_dir / CLIPPED_RASTER_DIRNAME).resolve()
    if not _is_relative_to(target_dir, resolved_workspace):
        raise IndexCalculationError(
            f"Refuse to delete path outside workspace: {target_dir}"
        )

    if target_dir.exists():
        shutil.rmtree(target_dir)
        logger.info("Removed intermediate directory path=%s", target_dir)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path.is_relative_to。"""

    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True
