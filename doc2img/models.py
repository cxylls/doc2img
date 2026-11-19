#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据模型与纯几何计算。

不依赖 tkinter / PIL，可独立进行单元测试，是包内被依赖最多的一层。
"""

from dataclasses import dataclass, field, replace
from typing import List, Sequence, Tuple

from .config import (
    DEFAULT_ALIGN,
    DEFAULT_MIN_PIXELS,
    DEFAULT_TOLERANCE,
    GAP_MODE_UNIFORM,
)


@dataclass(frozen=True)
class CropSettings:
    """空白行裁切参数。"""

    enabled: bool = True
    tolerance: int = DEFAULT_TOLERANCE
    min_pixels: int = DEFAULT_MIN_PIXELS
    padding: int = 0


@dataclass(frozen=True)
class StitchSettings:
    """拼接参数。gaps 为逐段间距，长度为页数 - 1。

    left_crop / right_crop 为成品左右各裁掉的空白列数，
    side_pad 为随后左右各补的空白列数，output_width 为输出宽度（0 表示不缩放）。
    """

    align: str = DEFAULT_ALIGN
    gaps: Tuple[int, ...] = field(default_factory=tuple)
    top_margin: int = 0
    bottom_margin: int = 0
    left_crop: int = 0
    right_crop: int = 0
    side_pad: int = 0
    output_width: int = 0


@dataclass(frozen=True)
class PageBox:
    """某一页在成品图中的位置与尺寸（未缩放的原始坐标）。"""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class PageLayout:
    """成品图整体版式。"""

    boxes: Tuple[PageBox, ...]
    max_width: int
    total_height: int


def resolve_gaps(
    page_count: int,
    mode: str,
    uniform_value: int,
    individual_values: Sequence[int],
) -> List[int]:
    """
    根据当前模式求出每一段页间距（段数 = 页数 - 1）。

    逐段模式下若已保存的值不足，用统一值补齐；多余则截断。
    两种模式共用同一份持久化数值，因此来回切换不会丢失单独设置的值。
    """
    segment_count = max(0, page_count - 1)
    if segment_count == 0:
        return []

    uniform = max(0, int(uniform_value))
    if mode == GAP_MODE_UNIFORM:
        return [uniform] * segment_count

    values = [max(0, int(v)) for v in individual_values]
    if len(values) < segment_count:
        values += [uniform] * (segment_count - len(values))
    return values[:segment_count]


def build_layout(
    sizes: Sequence[Tuple[int, int]],
    gaps: Sequence[int],
    align: str,
    top_margin: int,
    bottom_margin: int,
) -> PageLayout:
    """按对齐方式计算每一页在成品图中的坐标；画布宽度取所有页的最大宽度。"""
    if not sizes:
        return PageLayout(boxes=(), max_width=0, total_height=0)

    max_width = max(w for w, _ in sizes)
    boxes: List[PageBox] = []
    y = max(0, int(top_margin))

    for i, (width, height) in enumerate(sizes):
        if align == "left":
            x = 0
        elif align == "right":
            x = max_width - width
        else:  # center
            x = (max_width - width) // 2
        boxes.append(PageBox(x=x, y=y, width=width, height=height))
        y += height
        if i < len(gaps):
            y += gaps[i]

    return PageLayout(
        boxes=tuple(boxes),
        max_width=max_width,
        total_height=y + max(0, int(bottom_margin)),
    )


def apply_side_margins(
    layout: PageLayout,
    left_cut: int,
    right_cut: int,
    side_pad: int,
) -> PageLayout:
    """
    把版式左右各裁掉 left_cut / right_cut 列，再在两侧各补 side_pad 列空白。

    只平移页面盒子并改画布宽度，不动页面图片：裁掉的部分按定义是空白。
    """
    left_cut, right_cut = max(0, int(left_cut)), max(0, int(right_cut))
    side_pad = max(0, int(side_pad))

    width = layout.max_width - left_cut - right_cut + 2 * side_pad
    if width < 1:
        width = 1

    boxes = tuple(
        replace(box, x=box.x - left_cut + side_pad) for box in layout.boxes
    )
    return PageLayout(boxes=boxes, max_width=width, total_height=layout.total_height)


def compute_scale(
    zoom: str,
    max_width: int,
    available_width: int,
    fit_max_scale: float,
    min_scale: float,
    max_scale: float,
) -> float:
    """
    把缩放档位换算成实际缩放比。

    「适应宽度」按可用宽度等比缩放且不超过 fit_max_scale；
    其余按百分比取值，最后夹在 [min_scale, max_scale] 内。
    """
    if max_width <= 0:
        return 1.0

    if zoom == "适应宽度":
        scale = min(fit_max_scale, max(1, available_width - 6) / max_width)
    else:
        try:
            scale = int(zoom.rstrip("%")) / 100.0
        except ValueError:
            scale = 1.0

    return max(min_scale, min(max_scale, scale))
