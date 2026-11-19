#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面变量容器与文档状态。

UiVariables 集中保存全部 Tk 变量；DocumentState 保存与界面无关的处理状态。
"""

import os
import shutil
import tempfile
import tkinter as tk
from typing import List, Optional, Tuple

from .config import (
    DEFAULT_ALIGN,
    DEFAULT_DPI,
    DEFAULT_GAP_MODE,
    ZOOM_CHOICES,
)


class UiVariables:
    """所有与界面控件绑定的 Tk 变量。"""

    def __init__(self, root: tk.Misc):
        self.input = tk.StringVar(master=root, value="")
        self.dpi = tk.IntVar(master=root, value=DEFAULT_DPI)

        self.crop_enabled = tk.BooleanVar(master=root, value=True)

        self.crop_columns = tk.BooleanVar(master=root, value=True)
        self.side_margin = tk.IntVar(master=root, value=0)
        self.output_width = tk.IntVar(master=root, value=0)

        self.gap_mode = tk.StringVar(master=root, value=DEFAULT_GAP_MODE)
        self.gap_uniform = tk.IntVar(master=root, value=0)

        self.align = tk.StringVar(master=root, value=DEFAULT_ALIGN)
        self.top_margin = tk.IntVar(master=root, value=0)
        self.bottom_margin = tk.IntVar(master=root, value=0)

        self.zoom = tk.StringVar(master=root, value=ZOOM_CHOICES[0])
        self.status = tk.StringVar(master=root, value="请选择要处理的文档")


class DocumentState:
    """文档处理过程中的数据状态（不含任何 Tk 变量）。"""

    def __init__(self):
        self.pages: List = []            # 渲染出的原始页（PIL.Image）
        self.cropped: List = []          # 裁切后的页
        self.column_bounds: List[Optional[Tuple[int, int]]] = []  # 每页内容列范围
        self.gap_values: List[int] = []  # 逐段间距，切换模式时不丢失
        self.pdf_path: Optional[str] = None
        self.dpi_used: int = DEFAULT_DPI
        self._tmpdir: Optional[str] = None

    @property
    def has_pages(self) -> bool:
        return bool(self.cropped)

    def new_temp_pdf_path(self) -> str:
        """重建临时目录，返回其中用于存放中间 PDF 的路径。"""
        self.release_temp()
        self._tmpdir = tempfile.mkdtemp(prefix="doc2img_")
        return os.path.join(self._tmpdir, "document.pdf")

    def release_temp(self) -> None:
        """删除临时目录及其中的中间 PDF。"""
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
