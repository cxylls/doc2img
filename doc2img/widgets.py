#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可复用的 Tk 控件与定时器管理。"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, Optional


class ScrollableFrame(ttk.Frame):
    """带垂直滚动条的容器，内容放在 .inner 中。"""

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._win, width=e.width),
        )
        self._bind_wheel(self.canvas)
        self._bind_wheel(self.inner)

    def _bind_wheel(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_wheel)
        # Linux/X11 上用的是 Button-4 / Button-5
        widget.bind("<Button-4>", self._on_wheel)
        widget.bind("<Button-5>", self._on_wheel)

    def _on_wheel(self, event):
        if event.num == 4:
            step = -3
        elif event.num == 5:
            step = 3
        else:
            step = int(-1 * (event.delta / 120))
        if step:
            self._scroll_clamped(step)
        return "break"

    def _scroll_clamped(self, step: int) -> None:
        """滚到顶端/底端后不再继续滚动，避免内容被拖离边界。"""
        try:
            first, last = self.canvas.yview()
        except tk.TclError:
            return
        if (step < 0 and first <= 0.0) or (step > 0 and last >= 1.0):
            return
        self.canvas.yview_scroll(step, "units")


class JobTracker:
    """
    统一管理 root.after 定时任务。

    用键名追踪任务；再次调度同名任务会自动取消上一个（天然防抖），
    退出时一次性全部取消，避免回调残留在已销毁的窗口上。
    """

    def __init__(self, root: tk.Misc):
        self._root = root
        self._jobs: Dict[str, Optional[str]] = {}
        self._closed = False

    def schedule(self, key: str, delay_ms: int, func: Callable[[], None]) -> None:
        if self._closed:
            return
        self.cancel(key)
        self._jobs[key] = self._root.after(delay_ms, func)

    def cancel(self, key: str) -> None:
        job = self._jobs.get(key)
        if job is not None:
            try:
                self._root.after_cancel(job)
            except Exception:
                pass
            self._jobs[key] = None

    def close(self) -> None:
        """停止调度并取消全部待执行任务（窗口关闭时调用）。"""
        self._closed = True
        for key in list(self._jobs):
            self.cancel(key)


def spinbox_row(
    parent, label: str, variable, value_range, hint: str = "",
    label_width: int = 20, width: int = 7,
) -> ttk.Frame:
    """一行「标签 + Spinbox + 可选说明」的组合控件。"""
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=2)
    ttk.Label(row, text=label, width=label_width).pack(side="left")
    ttk.Spinbox(row, from_=value_range[0], to=value_range[1], width=width,
                textvariable=variable).pack(side="left")
    if hint:
        ttk.Label(row, text=hint, foreground="#777").pack(side="left", padx=6)
    return row


def labeled_combobox(
    parent, label: str, variable, values,
    width: int = 10, label_width: int = 20,
) -> ttk.Frame:
    """一行「标签 + 只读下拉框」的组合控件。"""
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=2)
    ttk.Label(row, text=label, width=label_width).pack(side="left")
    ttk.Combobox(row, width=width, state="readonly", textvariable=variable,
                 values=values).pack(side="left")
    return row
