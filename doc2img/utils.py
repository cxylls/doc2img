#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""与业务无关的工具函数。"""

import ctypes
import sys
import tkinter as tk
from typing import Optional


def enable_dpi_awareness() -> bool:
    """
    让 Windows 按真实 DPI 渲染窗口，而不是把低分辨率位图拉伸放大。

    必须在创建 tk.Tk() 之前调用，之后调用无效。
    未开启时进程被告知 96 DPI，在 150% 缩放的屏幕上界面会整体发虚。
    """
    if sys.platform != "win32":
        return False
    try:
        # 2 = PER_MONITOR_DPI_AWARE（Win8.1+），拖到不同缩放的显示器上都清晰
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        # 回退：Win7 / Vista 仅支持系统级 DPI 感知
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def safe_int(var, default: int, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    """
    安全读取 Tk 变量。

    Spinbox 编辑过程中可能出现空串或非法值；读失败时回退 default，
    并按 [lo, hi] 夹取。
    """
    try:
        value = int(var.get())
    except (TypeError, ValueError, tk.TclError):
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def clear_children(widget) -> None:
    """销毁某容器内的全部子控件（重建动态列表时使用）。"""
    for child in widget.winfo_children():
        child.destroy()
