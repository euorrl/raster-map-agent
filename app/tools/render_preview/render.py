"""指数 GeoTIFF 预览图渲染工具。"""

import warnings

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.enums import Resampling

from app.registry import get_index_config
from app.tools.render_preview.schemas import (
    RenderPreviewError,
    RenderPreviewRequest,
    RenderPreviewResult,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

LEGEND_MARGIN = 36
LEGEND_WIDTH = 520
LEGEND_HEIGHT = 152
LEGEND_OFFSET_X = 48
LEGEND_PADDING = 28
LEGEND_BAR_HEIGHT = 32
LEGEND_TEXT_SCALE = 4

DIGIT_FONT = {
    "-": ["000", "000", "111", "000", "000"],
    ".": ["0", "0", "0", "0", "1"],
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}

SUPPORTED_COLORMAPS: dict[str, tuple[np.ndarray, np.ndarray]] = {
    "greens": (
        np.array([247, 252, 245], dtype="float32"),
        np.array([0, 109, 44], dtype="float32"),
    ),
    "ylgn": (
        np.array([255, 255, 204], dtype="float32"),
        np.array([35, 132, 67], dtype="float32"),
    ),
    "blues": (
        np.array([247, 251, 255], dtype="float32"),
        np.array([8, 48, 107], dtype="float32"),
    ),
    "brbg": (
        np.array([84, 48, 5], dtype="float32"),
        np.array([0, 60, 48], dtype="float32"),
    ),
    "oranges": (
        np.array([255, 245, 235], dtype="float32"),
        np.array([127, 39, 4], dtype="float32"),
    ),
    "rdylgn": (
        np.array([165, 0, 38], dtype="float32"),
        np.array([0, 104, 55], dtype="float32"),
    ),
}


def render_index_preview(request: RenderPreviewRequest) -> RenderPreviewResult:
    """根据指数注册表配置，把单波段指数 GeoTIFF 渲染为 PNG 预览图。"""

    logger.info(
        "Rendering index preview index=%s input=%s output=%s",
        request.index_name,
        request.index_tif_path,
        request.output_path,
    )

    render_config = get_index_config(request.index_name).render_config
    if render_config.vmax <= render_config.vmin:
        raise RenderPreviewError(
            f"Invalid render range for {request.index_name}: "
            f"{render_config.vmin} to {render_config.vmax}"
        )

    if not request.index_tif_path.exists():
        raise RenderPreviewError(
            f"Index GeoTIFF does not exist: {request.index_tif_path}"
        )

    with rasterio.open(request.index_tif_path) as source:
        out_shape = _get_preview_shape(source.height, source.width, request.max_size)
        data = source.read(
            1,
            out_shape=out_shape,
            masked=True,
            resampling=Resampling.bilinear,
        ).astype("float32")

    valid_mask = ~np.ma.getmaskarray(data) & np.isfinite(data.filled(np.nan))
    data = data.filled(np.nan)

    scaled = _normalize_index_values(
        data=data,
        valid_mask=valid_mask,
        vmin=render_config.vmin,
        vmax=render_config.vmax,
    )
    rgba = _apply_colormap(scaled, valid_mask, render_config.colormap)
    if request.include_colorbar:
        rgba = _append_bottom_colorbar_legend(
            rgba=rgba,
            colormap=render_config.colormap,
            vmin=render_config.vmin,
            vmax=render_config.vmax,
        )

    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_png(request, rgba)

    logger.info("Saved index preview path=%s", request.output_path)
    return RenderPreviewResult(preview_path=str(request.output_path))


def _normalize_index_values(
    data: np.ndarray,
    valid_mask: np.ndarray,
    vmin: float,
    vmax: float,
) -> np.ndarray:
    """把指数值裁剪并归一化到 0 到 1，nodata 位置保持为 0。"""

    scaled = np.zeros(data.shape, dtype="float32")
    scaled[valid_mask] = (data[valid_mask] - vmin) / (vmax - vmin)
    return np.clip(scaled, 0.0, 1.0)


def _apply_colormap(
    scaled: np.ndarray,
    valid_mask: np.ndarray,
    colormap: str,
) -> np.ndarray:
    """把 0 到 1 的指数值映射成 RGBA uint8 图像。"""

    start_color, end_color = _get_colormap_colors(colormap)
    rgba = np.zeros((4, scaled.shape[0], scaled.shape[1]), dtype="uint8")

    for channel_index in range(3):
        channel = (
            start_color[channel_index] * (1.0 - scaled)
            + end_color[channel_index] * scaled
        )
        rgba[channel_index] = channel.astype("uint8")

    rgba[3] = np.where(valid_mask, 255, 0).astype("uint8")
    return rgba


def _append_bottom_colorbar_legend(
    rgba: np.ndarray,
    colormap: str,
    vmin: float,
    vmax: float,
) -> np.ndarray:
    """在图片底部新增区域，并在右下角绘制紧凑色带图例。"""

    height, width = rgba.shape[1], rgba.shape[2]
    if height < 96 or width < 120:
        return rgba

    output = np.full(
        (4, height + LEGEND_HEIGHT, width),
        fill_value=0,
        dtype="uint8",
    )
    output[:, :height, :] = rgba

    legend_width = min(LEGEND_WIDTH, width - LEGEND_MARGIN * 2)
    legend_height = LEGEND_HEIGHT - LEGEND_MARGIN
    legend_left = max(
        LEGEND_MARGIN,
        width - legend_width - LEGEND_MARGIN - LEGEND_OFFSET_X,
    )
    legend_top = height
    legend_right = legend_left + legend_width
    legend_bottom = legend_top + legend_height

    _blend_panel(
        rgba=output,
        top=legend_top,
        bottom=legend_bottom,
        left=legend_left,
        right=legend_right,
    )

    bar_left = legend_left + LEGEND_PADDING
    bar_right = legend_right - LEGEND_PADDING
    bar_top = legend_top + LEGEND_PADDING
    bar_bottom = bar_top + LEGEND_BAR_HEIGHT
    _draw_gradient_bar(
        rgba=output,
        colormap=colormap,
        top=bar_top,
        bottom=bar_bottom,
        left=bar_left,
        right=bar_right,
    )

    tick_bottom = bar_bottom + 8
    for tick_x in (bar_left, bar_right - 1):
        output[:3, bar_bottom:tick_bottom, tick_x : tick_x + 1] = 20
        output[3, bar_bottom:tick_bottom, tick_x : tick_x + 1] = 255

    label_top = tick_bottom + 8
    min_label = _format_tick_value(vmin)
    max_label = _format_tick_value(vmax)
    _draw_text(output, min_label, bar_left, label_top, color=(20, 20, 20))
    _draw_text(
        output,
        max_label,
        bar_right - _measure_text(max_label),
        label_top,
        color=(20, 20, 20),
    )
    return output


def _blend_panel(
    rgba: np.ndarray,
    top: int,
    bottom: int,
    left: int,
    right: int,
) -> None:
    """保留图例区域透明背景。"""

    rgba[3, top:bottom, left:right] = 0


def _draw_gradient_bar(
    rgba: np.ndarray,
    colormap: str,
    top: int,
    bottom: int,
    left: int,
    right: int,
) -> None:
    """绘制横向渐变色带。"""

    start_color, end_color = _get_colormap_colors(colormap)
    bar_width = max(1, right - left)
    gradient = np.linspace(0.0, 1.0, bar_width, dtype="float32")
    for channel_index in range(3):
        rgba[channel_index, top:bottom, left:right] = (
            start_color[channel_index] * (1.0 - gradient)
            + end_color[channel_index] * gradient
        ).astype("uint8")
    rgba[3, top:bottom, left:right] = 255


def _format_tick_value(value: float) -> str:
    """把色带端点格式化成短标签。"""

    return f"{value:.2f}".rstrip("0").rstrip(".")


def _measure_text(text: str) -> int:
    """测量内置点阵字体渲染宽度。"""

    width = 0
    for character in text:
        glyph = DIGIT_FONT.get(character)
        if glyph is None:
            continue
        width += len(glyph[0]) * LEGEND_TEXT_SCALE + LEGEND_TEXT_SCALE
    return max(0, width - LEGEND_TEXT_SCALE)


def _draw_text(
    rgba: np.ndarray,
    text: str,
    left: int,
    top: int,
    color: tuple[int, int, int],
) -> None:
    """用内置点阵字体绘制简短数字标签。"""

    cursor = left
    for character in text:
        glyph = DIGIT_FONT.get(character)
        if glyph is None:
            continue
        _draw_glyph(rgba, glyph, cursor, top, color)
        cursor += len(glyph[0]) * LEGEND_TEXT_SCALE + LEGEND_TEXT_SCALE


def _draw_glyph(
    rgba: np.ndarray,
    glyph: list[str],
    left: int,
    top: int,
    color: tuple[int, int, int],
) -> None:
    """绘制一个点阵字符。"""

    height, width = rgba.shape[1], rgba.shape[2]
    for row_index, row in enumerate(glyph):
        for column_index, value in enumerate(row):
            if value != "1":
                continue
            pixel_top = top + row_index * LEGEND_TEXT_SCALE
            pixel_left = left + column_index * LEGEND_TEXT_SCALE
            pixel_bottom = min(height, pixel_top + LEGEND_TEXT_SCALE)
            pixel_right = min(width, pixel_left + LEGEND_TEXT_SCALE)
            if pixel_top >= height or pixel_left >= width:
                continue
            rgba[:3, pixel_top:pixel_bottom, pixel_left:pixel_right] = np.array(
                color,
                dtype="uint8",
            ).reshape(3, 1, 1)
            rgba[3, pixel_top:pixel_bottom, pixel_left:pixel_right] = 255


def _get_colormap_colors(colormap: str) -> tuple[np.ndarray, np.ndarray]:
    """返回 V1 支持的简化色带端点。"""

    normalized_colormap = colormap.lower()
    try:
        return SUPPORTED_COLORMAPS[normalized_colormap]
    except KeyError as error:
        raise RenderPreviewError(f"Unsupported render colormap: {colormap}") from error


def _write_png(request: RenderPreviewRequest, rgba: np.ndarray) -> None:
    """写出 RGBA PNG 预览图。"""

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
        with rasterio.open(
            request.output_path,
            "w",
            driver="PNG",
            height=rgba.shape[1],
            width=rgba.shape[2],
            count=4,
            dtype="uint8",
        ) as destination:
            destination.write(rgba)


def _get_preview_shape(height: int, width: int, max_size: int) -> tuple[int, int]:
    """根据最长边限制计算预览图尺寸。"""

    longest_side = max(height, width)
    if longest_side <= max_size:
        return height, width

    scale = max_size / longest_side
    return max(1, round(height * scale)), max(1, round(width * scale))
