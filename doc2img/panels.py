#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""左侧设置面板。

只负责「摆放控件 + 把变化通知出去」，不直接操作业务状态；
回调由外部注入，因此本模块不导入 app，依赖方向保持单向。
"""

import tkinter as tk
from tkinter import ttk
from typing import List

from PIL import Image, ImageTk

from .config import (
    ALIGN_CHOICES,
    GAP_MODE_INDIVIDUAL,
    GAP_MODE_UNIFORM,
    GAP_RANGE,
    MARGIN_RANGE,
    OUTPUT_WIDTH_RANGE,
    THUMB_BG,
    THUMB_MAX_H,
    THUMB_W,
)
from .utils import clear_children
from .widgets import ScrollableFrame, labeled_combobox, spinbox_row


class ControlPanel:
    """裁切 / 左右空白 / 页间空白 / 拼接 / 导出 五组设置。"""

    def __init__(self, parent, variables, on_export, on_gap_value_changed):
        self.vars = variables
        self.on_export = on_export
        self.on_gap_value_changed = on_gap_value_changed

        self.gap_vars: List[tk.IntVar] = []
        self._thumb_photos: List[ImageTk.PhotoImage] = []

        scroller = ScrollableFrame(parent)
        scroller.pack(fill="both", expand=True)
        box = scroller.inner

        self._build_crop(box)
        self._build_columns(box)
        self._build_gap(box)
        self._build_stitch(box)
        self._build_export(box)

    # ------------------------------------------------------------------ #
    def _build_crop(self, parent) -> None:
        group = ttk.Labelframe(parent, text="空白行裁切", padding=8)
        group.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(group, text="裁掉每页首尾空白行",
                        variable=self.vars.crop_enabled).pack(anchor="w")

    def _build_columns(self, parent) -> None:
        group = ttk.Labelframe(parent, text="左右空白", padding=8)
        group.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(group, text="裁掉左右空白列",
                        variable=self.vars.crop_columns).pack(anchor="w")
        spinbox_row(group, "左右留白", self.vars.side_margin, MARGIN_RANGE,
                    "缩放前像素，0 = 不留")

    def _build_gap(self, parent) -> None:
        group = ttk.Labelframe(parent, text="页间空白", padding=8)
        group.pack(fill="x", pady=(0, 8))

        mode_row = ttk.Frame(group)
        mode_row.pack(fill="x")
        ttk.Radiobutton(mode_row, text="统一设置", value=GAP_MODE_UNIFORM,
                        variable=self.vars.gap_mode).pack(side="left")
        ttk.Radiobutton(mode_row, text="逐段单独设置", value=GAP_MODE_INDIVIDUAL,
                        variable=self.vars.gap_mode).pack(side="left", padx=(12, 0))

        # 两种模式共用一个容器，内部用 grid 占据同一格。
        # 不能用 pack_forget 来回打包：重新 pack 会追加到末尾导致顺序错乱，
        # 而 pack(before=...) 又要求参照物是同级控件，容易出错。
        holder = ttk.Frame(group)
        holder.pack(fill="x", pady=4)
        holder.columnconfigure(0, weight=1)

        self.uniform_frame = ttk.Frame(holder)
        self.uniform_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(self.uniform_frame, text="所有页间距").pack(side="left")
        ttk.Spinbox(self.uniform_frame, from_=GAP_RANGE[0], to=GAP_RANGE[1],
                    width=7, textvariable=self.vars.gap_uniform).pack(side="left", padx=4)
        ttk.Label(self.uniform_frame, text="px（行）").pack(side="left")

        self.individual_frame = ttk.Frame(holder)
        self.individual_frame.grid(row=0, column=0, sticky="ew")
        self.gap_rows_host = ttk.Frame(self.individual_frame)
        self.gap_rows_host.pack(fill="x")

        self.show_gap_placeholder("尚未载入文档")

        # 默认「统一设置」，先隐藏逐段面板
        self.individual_frame.grid_remove()

    def _build_stitch(self, parent) -> None:
        group = ttk.Labelframe(parent, text="拼接", padding=8)
        group.pack(fill="x", pady=(0, 8))

        labeled_combobox(group, "对齐方式", self.vars.align, ALIGN_CHOICES)
        spinbox_row(group, "长图顶部留白", self.vars.top_margin, MARGIN_RANGE)
        spinbox_row(group, "长图底部留白", self.vars.bottom_margin, MARGIN_RANGE)

    def _build_export(self, parent) -> None:
        group = ttk.Labelframe(parent, text="导出", padding=8)
        group.pack(fill="x")

        spinbox_row(group, "输出宽度", self.vars.output_width, OUTPUT_WIDTH_RANGE,
                    "px，0 = 保持原始宽度")

        self.export_btn = ttk.Button(group, text="导出图片",
                                     command=self.on_export, state="disabled")
        self.export_btn.pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------------ #
    def set_export_enabled(self, enabled: bool) -> None:
        self.export_btn.configure(state="normal" if enabled else "disabled")

    def show_gap_placeholder(self, text: str) -> None:
        clear_children(self.gap_rows_host)
        ttk.Label(self.gap_rows_host, text=text, foreground="#777").pack(anchor="w")

    def on_gap_mode_changed(self) -> None:
        if self.vars.gap_mode.get() == GAP_MODE_UNIFORM:
            self.individual_frame.grid_remove()
            self.uniform_frame.grid()
        else:
            self.uniform_frame.grid_remove()
            self.individual_frame.grid()

    def rebuild_gap_rows(self, page_count: int, values: List[int],
                         thumbnails: List[ImageTk.PhotoImage]) -> List[tk.IntVar]:
        """按页数重建逐段间距输入行，返回新建的 IntVar 列表。"""
        clear_children(self.gap_rows_host)
        self.gap_vars = []
        self._thumb_photos = list(thumbnails)

        if page_count < 2:
            self.show_gap_placeholder("只有 1 页，无需设置页间空白")
            return []

        for i in range(page_count - 1):
            row = ttk.Frame(self.gap_rows_host)
            row.pack(fill="x", pady=1)

            if i < len(self._thumb_photos):
                ttk.Label(row, image=self._thumb_photos[i]).pack(side="left")
            ttk.Label(row, text=f"第 {i + 1} 页 → 第 {i + 2} 页").pack(side="left", padx=6)

            var = tk.IntVar(value=values[i] if i < len(values) else 0)
            var.trace_add("write", lambda *_: self.on_gap_value_changed())
            self.gap_vars.append(var)
            ttk.Spinbox(row, from_=GAP_RANGE[0], to=GAP_RANGE[1],
                        width=7, textvariable=var).pack(side="right")
            ttk.Label(row, text="px").pack(side="right")

        return self.gap_vars

    def sync_gap_vars(self, value: int) -> None:
        """
        把统一值写入每一段输入框。

        调用方需自行屏蔽回调（见 app._apply_uniform），
        否则逐段赋值会反过来触发「某段被单独修改」的回调。
        """
        for var in self.gap_vars:
            var.set(value)

    @property
    def gap_values(self) -> List[int]:
        return [var.get() for var in self.gap_vars]


def build_thumbnails(images: List[Image.Image]) -> List[ImageTk.PhotoImage]:
    """为每一页生成窄缩略图，用于逐段间距行的页标识。"""
    photos: List[ImageTk.PhotoImage] = []
    for img in images:
        height = min(max(1, int(round(img.height * THUMB_W / img.width))), THUMB_MAX_H)
        thumb = img.resize((THUMB_W, height), Image.BILINEAR)
        canvas = Image.new("RGB", (THUMB_W, height), THUMB_BG)
        canvas.paste(thumb, (0, 0))
        photos.append(ImageTk.PhotoImage(canvas))
    return photos
