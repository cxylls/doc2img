#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预览渲染器：按需渲染可视区。

长图成品动辄数万像素高，整张渲染成一张 PhotoImage 既慢又占内存，
早先还因此不得不限制缩放比例。这里改为只绘制当前视口附近的一段
（上下各留 BAND_MARGIN 余量），滚动时重画，于是：

    * 缩放不再受成品高度限制，任意档位都真实生效
    * 内存与渲染量只与视口大小有关，与文档页数无关
"""

import tkinter as tk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageTk

from .config import (
    BAND_MARGIN,
    FIT_WIDTH_MAX_SCALE,
    MAX_SCALE,
    MIN_SCALE,
    PREVIEW_FALLBACK_W,
    PREVIEW_GAP_INPUT_HEIGHT,
    PREVIEW_RAIL_BG,
    PREVIEW_RAIL_DIVIDER,
    PREVIEW_RAIL_PAD,
    PREVIEW_RAIL_W,
)
from .models import PageLayout, compute_scale


class PreviewRenderer:
    """
    负责把版式与页面图片绘制到 Canvas 上。

    只做渲染，不负责调度（滚动回调、防抖、任务取消都在 app 层），
    因此本模块不依赖 app，也不产生循环导入。
    """

    def __init__(self, canvas: tk.Canvas):
        self._canvas = canvas
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._layout: Optional[PageLayout] = None
        self._images: List[Image.Image] = []

        self.scale: float = 1.0
        self.full_width: int = 1
        self.full_height: int = 1
        self.background: Tuple[int, int, int] = (255, 255, 255)
        self.rail_width: int = 0  # 左侧输入竖栏占用的屏幕像素

        # 逐段模式下的页间空白输入框：段序号 -> (canvas item, widget)
        self._gap_factory: Optional[Callable[[int], Optional[tk.Widget]]] = None
        self._gap_widgets: Dict[int, Tuple[int, tk.Widget]] = {}

    @property
    def has_content(self) -> bool:
        return bool(self._images)

    @property
    def band_height(self) -> int:
        return self._photo.height() if self._photo is not None else 0

    # ------------------------------------------------------------------ #
    def update(
        self,
        images: Sequence[Image.Image],
        layout: PageLayout,
        background: Tuple[int, int, int],
        zoom: str,
        show_rail: bool = False,
    ) -> None:
        """重新计算缩放与整图尺寸，并刷新滚动区域。"""
        self._images = list(images)
        self._layout = layout
        self.background = background

        # 竖栏是界面元素，宽高不随缩放变化，因此从可用宽度里直接扣掉
        show = show_rail and len(self._images) > 1
        self.rail_width = self._rail_pixels() if show else 0
        if not self.rail_width:
            self.reset_gap_widgets()

        self.scale = compute_scale(
            zoom=zoom,
            max_width=layout.max_width,
            available_width=self._available_width(),
            fit_max_scale=FIT_WIDTH_MAX_SCALE,
            min_scale=MIN_SCALE,
            max_scale=MAX_SCALE,
        )
        self.full_width = max(
            1, int(round(layout.max_width * self.scale)) + self.rail_width
        )
        self.full_height = max(1, int(round(layout.total_height * self.scale)))
        self._apply_scrollregion()

    def clear(self) -> None:
        self.reset_gap_widgets()
        self._canvas.delete("all")
        self._canvas.configure(scrollregion=(0, 0, 1, 1))
        self._images = []
        self._layout = None
        self._photo = None
        self.rail_width = 0

    def render_band(self) -> None:
        """绘制当前视口附近的一段。"""
        layout = self._layout
        if layout is None or not self._images:
            return

        y0, y1 = self._visible_band()
        if y1 <= y0:
            return

        band = Image.new("RGB", (self.full_width, y1 - y0), self.background)
        if self.rail_width:
            band.paste(PREVIEW_RAIL_BG, (0, 0, self.rail_width, y1 - y0))
            band.paste(
                PREVIEW_RAIL_DIVIDER,
                (self.rail_width - 1, 0, self.rail_width, y1 - y0),
            )

        # 该 band 对应的原始（未缩放）纵坐标区间
        src_top = y0 / self.scale
        src_bottom = y1 / self.scale

        for index, box in enumerate(layout.boxes):
            if index < len(self._images):
                self._paste_slice(band, index, box, src_top, src_bottom, y0)

        self._photo = ImageTk.PhotoImage(band)
        self._canvas.delete("band")  # 只换图，不动输入框
        self._canvas.create_image(0, y0, anchor="nw", image=self._photo, tags="band")
        self._apply_scrollregion()
        self._sync_gap_widgets(y0, y1)

    # ------------------------------------------------------------------ #
    #  逐段空白的输入框
    # ------------------------------------------------------------------ #
    def set_gap_factory(
        self, factory: Optional[Callable[[int], Optional[tk.Widget]]]
    ) -> None:
        """注入「为第 index 段创建输入框」的工厂；传 None 表示不显示。"""
        self._gap_factory = factory
        self.reset_gap_widgets()

    def reset_gap_widgets(self) -> None:
        """销毁已创建的输入框（页数或所绑定的变量变化后调用）。"""
        for item, widget in self._gap_widgets.values():
            try:
                self._canvas.delete(item)
            except tk.TclError:
                pass
            try:
                widget.destroy()
            except tk.TclError:
                pass
        self._gap_widgets.clear()

    def _sync_gap_widgets(self, band_top: int, band_bottom: int) -> None:
        """把输入框摆到每两页交界处的左侧，只创建可视范围内那几段。"""
        if self._gap_factory is None or not self.rail_width or self._layout is None:
            return

        centers = self._gap_centers()
        for index in list(self._gap_widgets):
            if index >= len(centers):
                item, widget = self._gap_widgets.pop(index)
                self._canvas.delete(item)
                widget.destroy()
            else:
                self._canvas.coords(self._gap_widgets[index][0],
                                    self._gap_input_x(), centers[index])

        margin = PREVIEW_GAP_INPUT_HEIGHT
        for index, center in enumerate(centers):
            if index in self._gap_widgets:
                continue
            if center < band_top - margin or center > band_bottom + margin:
                continue
            widget = self._gap_factory(index)
            if widget is None:
                continue
            item = self._canvas.create_window(
                self._gap_input_x(), center, window=widget, anchor="e"
            )
            self._gap_widgets[index] = (item, widget)

        # 图片每帧重建，确保输入框始终压在图片之上
        for item, _widget in self._gap_widgets.values():
            self._canvas.tag_raise(item)

    def _gap_centers(self) -> List[float]:
        """每一段页间空白在画布上的中心纵坐标。"""
        boxes = self._layout.boxes if self._layout else ()
        return [
            (boxes[i].y + boxes[i].height + boxes[i + 1].y) / 2.0 * self.scale
            for i in range(len(boxes) - 1)
        ]

    def _gap_input_x(self) -> int:
        return self.rail_width - PREVIEW_RAIL_PAD

    def _rail_pixels(self) -> int:
        """竖栏宽度随屏幕 DPI 放大，避免高缩放下输入框被裁掉。"""
        try:
            factor = self._canvas.winfo_fpixels("1i") / 96.0
        except tk.TclError:
            factor = 1.0
        return int(round(PREVIEW_RAIL_W * max(1.0, factor)))

    def band_key(self) -> Optional[Tuple[float, float, int, int, float]]:
        """
        当前视口指纹，用于判断是否真的需要重画。

        渲染会修改 scrollregion，进而触发滚动回调，回调又调度渲染；
        用指纹比对可打断这个环路，避免空转。
        """
        try:
            first, last = self._canvas.yview()
        except tk.TclError:
            return None
        return (round(first, 4), round(last, 4),
                self.full_width, self.full_height, self.scale)

    def viewport_center(self) -> Optional[float]:
        """记录当前视口中心比例，供缩放切换后恢复位置。"""
        try:
            first, last = self._canvas.yview()
        except tk.TclError:
            return None
        return (first + last) / 2.0

    def restore_center(self, center: float) -> None:
        """按之前记录的中心比例恢复滚动位置。"""
        if self.full_height <= 0:
            return
        view_height = max(1, self._canvas.winfo_height())
        self._canvas.yview_moveto(center - (view_height / self.full_height) / 2.0)

    # ------------------------------------------------------------------ #
    def _available_width(self) -> int:
        width = self._canvas.winfo_width()
        if width < 50:
            width = PREVIEW_FALLBACK_W
        return width - self.rail_width

    def _visible_band(self) -> Tuple[int, int]:
        try:
            first, last = self._canvas.yview()
        except tk.TclError:
            first, last = 0.0, 1.0
        return (
            max(0, int(first * self.full_height) - BAND_MARGIN),
            min(self.full_height, int(last * self.full_height) + BAND_MARGIN),
        )

    def _paste_slice(self, band, index, box, src_top, src_bottom, y0) -> None:
        """把某一页与 band 相交的部分裁出来、缩放后贴到 band 上。"""
        # 左右裁切后页面盒子可能超出画布，先按画布范围裁剪，防止压到左侧竖栏
        canvas_right = self._layout.max_width if self._layout else box.x + box.width
        left = max(0, box.x)
        right = min(canvas_right, box.x + box.width)
        if right <= left:
            return

        if box.y >= src_bottom or box.y + box.height <= src_top:
            return

        slice_top = max(box.y, src_top)
        slice_bottom = min(box.y + box.height, src_bottom)
        if slice_bottom <= slice_top:
            return

        offset = int(slice_top - box.y)
        height = max(1, int(slice_bottom - slice_top))
        src_left = left - box.x
        src_right = right - box.x
        source = self._images[index].crop(
            (src_left, offset, src_right, min(box.height, offset + height))
        )
        source = source.resize(
            (
                max(1, int(round((src_right - src_left) * self.scale))),
                max(1, int(round((slice_bottom - slice_top) * self.scale))),
            ),
            Image.BILINEAR,
        )
        band.paste(
            source,
            (
                self.rail_width + int(round(left * self.scale)),
                int(round(slice_top * self.scale)) - y0,
            ),
        )

    def _apply_scrollregion(self) -> None:
        self._canvas.configure(scrollregion=(0, 0, self.full_width, self.full_height))
