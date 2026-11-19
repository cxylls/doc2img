#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主应用：把各层组装起来。

职责边界：
    * 持有界面变量（UiVariables）与文档状态（DocumentState）
    * 把用户操作转成后台任务（tasks），把结果同步回界面
    * 调度防抖任务（JobTracker）与结果轮询
    * 其余逻辑分别下沉到 models（纯计算）／preview（渲染）／panels（控件）
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

import numpy as np

from docx_to_long_image import estimate_background

from .config import (
    DELAY_BAND,
    DELAY_POLL,
    DELAY_PREVIEW,
    DELAY_RECROP,
    DELAY_RERENDER,
    DPI_RANGE,
    GAP_MODE_INDIVIDUAL,
    GAP_RANGE,
    MARGIN_RANGE,
    OUTPUT_WIDTH_RANGE,
    PREVIEW_CANVAS_BG,
    PREVIEW_GAP_INPUT_WIDTH,
    WINDOW_GEOMETRY,
    WINDOW_MINSIZE,
    WINDOW_TITLE,
    ZOOM_CHOICES,
    ZOOM_FIT,
)
from .models import (
    CropSettings,
    PageLayout,
    StitchSettings,
    apply_side_margins,
    build_layout,
    resolve_gaps,
)
from .panels import ControlPanel, build_thumbnails
from .preview import PreviewRenderer
from .settings import load_defaults
from .state import DocumentState, UiVariables
from .tasks import AsyncRunner, crop_pages, export_long_image, load_pages
from .utils import enable_dpi_awareness, safe_int
from .widgets import JobTracker


class Doc2ImgApp:
    """文档转长图主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_GEOMETRY)
        root.minsize(*WINDOW_MINSIZE)

        self.state = DocumentState()
        self.vars = UiVariables(root)
        self.defaults = load_defaults()

        self._updating = False   # 批量写回输入框时屏蔽回调
        self._closed = False
        self._thumbnails: List = []
        self._band_key: Optional[Tuple] = None  # 上次渲染时的视口指纹

        self.jobs = JobTracker(root)
        self.runner = AsyncRunner(
            root,
            on_start=lambda: self._set_busy(True),
            on_finish=lambda: self._set_busy(False),
            on_error=self._on_task_error,
        )

        self._build_ui()
        self._apply_defaults()   # 必须在挂 trace 之前，避免触发重算
        self._attach_traces()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_poll()

    # ------------------------------------------------------------------ #
    #  界面搭建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        top.pack(side="top", fill="x")

        ttk.Label(top, text="源文件:").grid(row=0, column=0, sticky="w")
        source_entry = ttk.Entry(top, textvariable=self.vars.input)
        source_entry.grid(row=0, column=1, sticky="ew", padx=4)
        source_entry.bind("<Return>", lambda _event: self.start_load())
        self.open_btn = ttk.Button(top, text="打开文件", command=self._browse_input)
        self.open_btn.grid(row=0, column=2)

        ttk.Label(top, text="DPI:").grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Spinbox(top, from_=DPI_RANGE[0], to=DPI_RANGE[1], width=6,
                    textvariable=self.vars.dpi).grid(row=0, column=4, padx=4)

        top.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(side="top", fill="x", padx=8)

        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(side="top", fill="both", expand=True, padx=8, pady=6)
        self._build_left(paned)
        self._build_preview(paned)

        status = ttk.Frame(self.root, padding=(8, 2, 8, 6))
        status.pack(side="bottom", fill="x")
        ttk.Label(status, textvariable=self.vars.status, anchor="w").pack(fill="x")

    def _build_left(self, paned) -> None:
        holder = ttk.Frame(paned, width=380)
        paned.add(holder, weight=0)
        self.panel = ControlPanel(
            holder,
            self.vars,
            on_export=self.start_export,
            on_gap_value_changed=self._on_gap_value_changed,
        )

    def _build_preview(self, paned) -> None:
        holder = ttk.Frame(paned)
        paned.add(holder, weight=1)

        bar = ttk.Frame(holder)
        bar.pack(fill="x")
        ttk.Label(bar, text="实时预览").pack(side="left")
        ttk.Label(bar, text="缩放:").pack(side="left", padx=(16, 0))
        ttk.Combobox(bar, width=10, state="readonly", textvariable=self.vars.zoom,
                     values=ZOOM_CHOICES).pack(side="left")
        ttk.Button(bar, text="适应窗口", command=self._fit_preview).pack(side="left", padx=(8, 0))
        self.size_label = ttk.Label(bar, text="", foreground="#555")
        self.size_label.pack(side="right")

        wrap = ttk.Frame(holder)
        wrap.pack(fill="both", expand=True, pady=(4, 0))

        self.pv_canvas = tk.Canvas(wrap, bg=PREVIEW_CANVAS_BG, highlightthickness=0)
        self.pv_vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.pv_canvas.yview)
        self.pv_hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.pv_canvas.xview)
        # 竖直滚动时需要按需重画可视区，所以走自定义回调而不是直接 vsb.set
        self.pv_canvas.configure(yscrollcommand=self._on_pv_yscroll,
                                 xscrollcommand=self._on_pv_xscroll)

        self.pv_canvas.grid(row=0, column=0, sticky="nsew")
        self.pv_vsb.grid(row=0, column=1, sticky="ns")
        self.pv_hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.pv_canvas.bind("<MouseWheel>", self._preview_wheel)
        self.pv_canvas.bind("<Shift-MouseWheel>", self._preview_wheel_h)
        self.pv_canvas.bind("<Configure>", lambda e: self._schedule_preview())

        self.preview = PreviewRenderer(self.pv_canvas)
        self.preview.set_gap_factory(self._create_gap_input)

    def _apply_defaults(self) -> None:
        """把 settings.ini 里的默认参数写进界面变量。"""
        self.vars.dpi.set(self.defaults.dpi)
        self.vars.gap_uniform.set(self.defaults.gap)
        self.vars.top_margin.set(self.defaults.top_margin)
        self.vars.bottom_margin.set(self.defaults.bottom_margin)
        self.vars.side_margin.set(self.defaults.side_margin)
        self.vars.output_width.set(self.defaults.output_width)

    # ------------------------------------------------------------------ #
    #  预览交互
    # ------------------------------------------------------------------ #
    def _preview_wheel(self, event):
        if event.num == 4:
            self.pv_canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self.pv_canvas.yview_scroll(3, "units")
        elif event.delta:
            self.pv_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _preview_wheel_h(self, event):
        if event.delta:
            self.pv_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_pv_yscroll(self, first, last) -> None:
        self.pv_vsb.set(first, last)
        self._schedule_band()

    def _on_pv_xscroll(self, first, last) -> None:
        self.pv_hsb.set(first, last)

    def _schedule_band(self) -> None:
        """视口变化时才重画，避免渲染自身触发滚动回调造成空转。"""
        if self._closed:
            return
        key = self.preview.band_key()
        if key is None or key == self._band_key:
            return
        self._band_key = key
        self.jobs.schedule("band", DELAY_BAND, self.preview.render_band)

    def _fit_preview(self) -> None:
        self.vars.zoom.set(ZOOM_FIT)
        self._render_preview()

    # ------------------------------------------------------------------ #
    #  事件绑定
    # ------------------------------------------------------------------ #
    def _attach_traces(self) -> None:
        # 裁切开关变化 -> 重新裁切（较慢，走后台线程）
        self.vars.crop_enabled.trace_add("write", lambda *_: self._schedule_recrop())

        # 拼接参数变化 -> 仅重绘预览（快）
        for var in (self.vars.align, self.vars.top_margin,
                    self.vars.bottom_margin, self.vars.zoom,
                    self.vars.crop_columns, self.vars.side_margin,
                    self.vars.output_width):
            var.trace_add("write", lambda *_: self._schedule_preview())

        self.vars.gap_uniform.trace_add("write", lambda *_: self._apply_uniform())
        self.vars.gap_mode.trace_add("write", lambda *_: self._on_gap_mode_changed())
        self.vars.dpi.trace_add("write", lambda *_: self._schedule_rerender())

    # ------------------------------------------------------------------ #
    #  文件选择
    # ------------------------------------------------------------------ #
    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择文档",
            filetypes=[("Word / PDF", "*.docx *.doc *.pdf"),
                       ("Word 文档", "*.docx *.doc"),
                       ("PDF", "*.pdf"),
                       ("所有文件", "*.*")],
        )
        if path:
            self.vars.input.set(path)
            self.start_load()

    # ------------------------------------------------------------------ #
    #  任务调度
    # ------------------------------------------------------------------ #
    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.progress.start(12)
            self.open_btn.configure(state="disabled")
            self.panel.set_export_enabled(False)
        else:
            self.progress.stop()
            self.open_btn.configure(state="normal")
            if self.state.has_pages:
                self.panel.set_export_enabled(True)

    def _on_task_error(self, error: BaseException) -> None:
        self.vars.status.set(f"失败：{error}")
        messagebox.showerror("出错了", str(error))

    def _schedule_poll(self) -> None:
        """轮询后台任务结果；自身持续续期，关闭时由 JobTracker 取消。"""
        self.runner.poll()
        if self._closed:
            return
        try:
            if self.root.winfo_exists():
                self.jobs.schedule("poll", DELAY_POLL, self._schedule_poll)
        except tk.TclError:
            return

    def _schedule_recrop(self) -> None:
        if self._closed or self._updating or not self.state.pages:
            return
        self.jobs.schedule("recrop", DELAY_RECROP, self.start_recrop)

    def _schedule_preview(self) -> None:
        if self._closed:
            return
        self.jobs.schedule("preview", DELAY_PREVIEW, self._render_preview)

    def _schedule_rerender(self) -> None:
        if self._closed or self._updating or not self.state.pdf_path:
            return
        self.jobs.schedule("rerender", DELAY_RERENDER, self.start_rerender)

    # ------------------------------------------------------------------ #
    #  载入 / 渲染 / 裁切
    # ------------------------------------------------------------------ #
    def start_load(self) -> None:
        source = self.vars.input.get().strip().strip('"')
        if not source:
            messagebox.showinfo("提示", "请先选择源文件")
            return
        if not os.path.exists(source):
            messagebox.showerror("错误", f"文件不存在：\n{source}")
            return

        # Tk 变量只能在主线程读取，先取值再交给后台线程
        dpi = safe_int(self.vars.dpi, self.defaults.dpi, *DPI_RANGE)
        self.vars.status.set("正在转换并渲染文档...")
        self.runner.submit(
            lambda: load_pages(source, dpi, self.state.new_temp_pdf_path),
            self._on_pages_loaded,
        )

    def _on_pages_loaded(self, pages) -> None:
        self.state.pages = pages
        self.state.column_bounds = []
        self.state.dpi_used = safe_int(self.vars.dpi, self.defaults.dpi, *DPI_RANGE)
        self.vars.status.set(f"已载入 {len(pages)} 页（{self.state.dpi_used} DPI）")
        self.start_recrop()

    def start_rerender(self) -> None:
        if not self.state.pdf_path or not os.path.exists(self.state.pdf_path):
            return
        dpi = safe_int(self.vars.dpi, self.defaults.dpi, *DPI_RANGE)
        self.vars.status.set("正在重新渲染...")
        self.runner.submit(
            lambda: load_pages(self.state.pdf_path, dpi, self.state.new_temp_pdf_path),
            self._on_pages_loaded,
        )

    def start_recrop(self) -> None:
        if not self.state.pages:
            return
        # 容差等细节不再暴露给用户，固定使用核心模块的默认判定
        settings = CropSettings(enabled=self.vars.crop_enabled.get())
        self.vars.status.set("正在检测空白行...")
        self.runner.submit(lambda: crop_pages(self.state.pages, settings), self._on_cropped)

    def _on_cropped(self, result) -> None:
        cropped, column_bounds = result
        self.state.cropped = cropped
        self.state.column_bounds = column_bounds
        self._thumbnails = build_thumbnails(cropped)
        self._rebuild_gap_rows()
        self._render_preview()
        # 任务结束时 _set_busy(False) 先于本回调执行，那时 cropped 还是空的，
        # 导出按钮会保持禁用；这里补一次，首次载入后才能真正点击导出。
        self.panel.set_export_enabled(bool(cropped))

    # ------------------------------------------------------------------ #
    #  页间空白
    # ------------------------------------------------------------------ #
    def _current_gaps(self) -> List[int]:
        return resolve_gaps(
            page_count=len(self.state.cropped),
            mode=self.vars.gap_mode.get(),
            uniform_value=safe_int(self.vars.gap_uniform, 0, *GAP_RANGE),
            individual_values=self.state.gap_values,
        )

    def _on_gap_mode_changed(self) -> None:
        self.panel.on_gap_mode_changed()
        self._schedule_preview()

    def _apply_uniform(self) -> None:
        """统一值变化时写回每一段，使切到「逐段」时数值连续。"""
        if self._updating:
            return
        value = safe_int(self.vars.gap_uniform, 0, *GAP_RANGE)
        self.state.gap_values = [value] * max(0, len(self.state.cropped) - 1)
        self._updating = True  # 屏蔽回调，避免逐段赋值反过来覆盖统一值
        try:
            self.panel.sync_gap_vars(value)
        finally:
            self._updating = False
        self._schedule_preview()

    def _on_gap_value_changed(self) -> None:
        """某一段被单独修改后，回写到持久化列表。"""
        if self._updating:
            return
        self.state.gap_values = [safe_int(var, 0, *GAP_RANGE) for var in self.panel.gap_vars]
        self._schedule_preview()

    def _rebuild_gap_rows(self) -> None:
        new_vars = self.panel.rebuild_gap_rows(
            page_count=len(self.state.cropped),
            values=self._current_gaps(),
            thumbnails=self._thumbnails,
        )
        self.state.gap_values = [safe_int(var, 0, *GAP_RANGE) for var in new_vars]
        self.preview.reset_gap_widgets()  # 旧输入框绑的是旧变量，一并丢弃

    def _create_gap_input(self, index: int) -> Optional[ttk.Spinbox]:
        """预览左侧栏里第 index 段的输入框；与逐段面板共用同一个变量。"""
        if index >= len(self.panel.gap_vars):
            return None
        spinbox = ttk.Spinbox(
            self.pv_canvas,
            from_=GAP_RANGE[0],
            to=GAP_RANGE[1],
            width=PREVIEW_GAP_INPUT_WIDTH,
            justify="center",
            textvariable=self.panel.gap_vars[index],
        )
        # 指针停在输入框上滚轮时滚动预览，而不是偷偷改掉数值
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            spinbox.bind(sequence, self._preview_wheel)
        return spinbox

    # ------------------------------------------------------------------ #
    #  左右空白 / 输出宽度
    # ------------------------------------------------------------------ #
    def _column_cuts(self, layout: PageLayout) -> Tuple[int, int]:
        """按当前对齐方式合并各页内容列，得到整幅图左右要裁掉的列数。"""
        if not self.vars.crop_columns.get() or not self.state.column_bounds:
            return 0, 0

        lefts: List[int] = []
        rights: List[int] = []
        for box, bounds in zip(layout.boxes, self.state.column_bounds):
            if bounds is None:
                continue
            lefts.append(box.x + bounds[0])
            rights.append(box.x + bounds[1])
        if not lefts:
            return 0, 0

        left = max(0, min(lefts))
        right = min(layout.max_width - 1, max(rights))
        if right < left:
            return 0, 0
        return left, layout.max_width - 1 - right

    def _side_params(
        self, layout: PageLayout
    ) -> Tuple[PageLayout, Tuple[int, int], int]:
        """返回 (应用左右裁切/留白后的版式, (左裁, 右裁), 左右留白)。

        留白与上下留白、页间间隔一样按缩放前的像素计算，
        导出缩放到目标宽度时整体等比变化。
        """
        left_cut, right_cut = self._column_cuts(layout)
        pad = safe_int(self.vars.side_margin, 0, *MARGIN_RANGE)
        return (
            apply_side_margins(layout, left_cut, right_cut, pad),
            (left_cut, right_cut),
            pad,
        )

    # ------------------------------------------------------------------ #
    #  预览
    # ------------------------------------------------------------------ #
    def _background_color(self) -> Tuple[int, int, int]:
        if not self.state.cropped:
            return (255, 255, 255)
        arr = np.asarray(self.state.cropped[0].convert("RGB"), dtype=np.int16)
        return tuple(int(v) for v in estimate_background(arr))

    def _size_text(self, layout: PageLayout) -> str:
        text = f"成品 {layout.max_width} x {layout.total_height} px"
        output_width = safe_int(self.vars.output_width, 0, *OUTPUT_WIDTH_RANGE)
        if output_width > 0 and layout.max_width > 0:
            height = max(1, round(layout.total_height * output_width / layout.max_width))
            text += f"    输出 {output_width} x {height} px"
        return text

    def _render_preview(self) -> None:
        if not self.state.cropped:
            self.preview.clear()
            self.size_label.configure(text="")
            return

        layout = build_layout(
            [(img.width, img.height) for img in self.state.cropped],
            self._current_gaps(),
            self.vars.align.get(),
            safe_int(self.vars.top_margin, 0, *MARGIN_RANGE),
            safe_int(self.vars.bottom_margin, 0, *MARGIN_RANGE),
        )
        layout, _cuts, _pad = self._side_params(layout)

        # 缩放切换后尽量保持视口中心不动
        center = self.preview.viewport_center() if self.preview.has_content else None

        self.preview.update(
            self.state.cropped, layout, self._background_color(),
            self.vars.zoom.get(),
            show_rail=self.vars.gap_mode.get() == GAP_MODE_INDIVIDUAL,
        )
        self._band_key = None
        self.preview.render_band()

        if center is not None:
            self.preview.restore_center(center)
            self._band_key = None
            self.preview.render_band()

        self.size_label.configure(
            text=f"{self._size_text(layout)}    预览缩放 {self.preview.scale * 100:.0f}%"
        )
        self.vars.status.set(
            f"共 {len(self.state.cropped)} 页    {self._size_text(layout)}"
            f"    预览缩放 {self.preview.scale * 100:.0f}%"
        )

    # ------------------------------------------------------------------ #
    #  导出
    # ------------------------------------------------------------------ #
    def _ask_output_path(self) -> str:
        """导出对话框：落在源文档目录，文件名自动取源文档名（不带后缀）。"""
        source = self.vars.input.get().strip().strip('"')
        folder = os.path.dirname(os.path.abspath(source)) if source else ""
        if not folder or not os.path.isdir(folder):
            folder = os.getcwd()
        name = os.path.splitext(os.path.basename(source))[0] if source else "长图"

        return filedialog.asksaveasfilename(
            title="导出图片",
            initialdir=folder,
            initialfile=name,
            defaultextension=".jpg",
            filetypes=[("JPEG 图片", "*.jpg *.jpeg"),
                       ("PNG 图片", "*.png"),
                       ("所有文件", "*.*")],
        )

    def start_export(self) -> None:
        if not self.state.has_pages:
            messagebox.showinfo("提示", "还没有可导出的内容")
            return

        output = self._ask_output_path()
        if not output:
            return

        pages = list(self.state.cropped)

        # 左右裁切与留白沿用预览那套计算，保证导出与所见一致
        base_layout = build_layout(
            [(img.width, img.height) for img in pages],
            self._current_gaps(),
            self.vars.align.get(),
            safe_int(self.vars.top_margin, 0, *MARGIN_RANGE),
            safe_int(self.vars.bottom_margin, 0, *MARGIN_RANGE),
        )
        _, (left_crop, right_crop), side_pad = self._side_params(base_layout)

        settings = StitchSettings(
            align=self.vars.align.get(),
            gaps=tuple(self._current_gaps()),
            top_margin=safe_int(self.vars.top_margin, 0, *MARGIN_RANGE),
            bottom_margin=safe_int(self.vars.bottom_margin, 0, *MARGIN_RANGE),
            left_crop=left_crop,
            right_crop=right_crop,
            side_pad=side_pad,
            output_width=safe_int(self.vars.output_width, 0, *OUTPUT_WIDTH_RANGE),
        )
        background = self._background_color()

        self.vars.status.set("正在导出图片...")
        self.runner.submit(
            lambda: export_long_image(pages, settings, background, output),
            self._on_exported,
        )

    def _on_exported(self, result) -> None:
        path, size = result
        self.vars.status.set(f"已导出：{path}（{size[0]} x {size[1]}）")
        messagebox.showinfo("导出完成", f"已保存：\n{path}\n\n尺寸：{size[0]} x {size[1]}")

    # ------------------------------------------------------------------ #
    def _on_close(self) -> None:
        self._closed = True
        self.jobs.close()
        self.state.release_temp()
        self.root.destroy()


def main() -> int:
    """启动图形界面，返回进程退出码。"""
    enable_dpi_awareness()  # 必须在 tk.Tk() 之前调用
    root = tk.Tk()
    Doc2ImgApp(root)
    root.mainloop()
    return 0
