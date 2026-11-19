#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台任务与异步执行框架。

耗时操作（格式转换、PDF 渲染、空白行检测、导出）都在这里以后台线程执行，
结果经队列交回主线程，避免界面卡死。

约定：任务函数不接触任何 Tk 变量—— Tk 变量只能在主线程读取，
需要的值由调用方在主线程取好后以参数传入。
"""

import queue
import sys
import threading
import tkinter as tk
from typing import Any, Callable, List, Optional, Tuple

from PIL import Image

from docx_to_long_image import (
    add_margins,
    crop_blank_lines,
    detect_content_columns,
    docx_to_pdf,
    estimate_pages_background,
    pdf_to_images,
    save_long_image,
    stitch_vertical_variable,
)

from .models import CropSettings, StitchSettings


# --------------------------------------------------------------------------- #
#  后台任务（在线程中执行，不得触碰 Tk）
# --------------------------------------------------------------------------- #
def load_pages(source_path: str, dpi: int, temp_pdf_factory) -> List[Image.Image]:
    """
    把 docx/doc/pdf 渲染为逐页图片。

    temp_pdf_factory 返回中间 PDF 的保存路径；传入的是可调用对象而非路径，
    是为了让临时目录在主线程创建，避免线程间共享可变状态。
    """
    if source_path.lower().endswith(".pdf"):
        pdf_path = source_path
    else:
        pdf_path = temp_pdf_factory()
        docx_to_pdf(source_path, pdf_path)

    return pdf_to_images(pdf_path, dpi=dpi)


def crop_pages(
    pages: List[Image.Image], settings: CropSettings
) -> Tuple[List[Image.Image], List[Optional[Tuple[int, int]]]]:
    """
    按裁切设置处理每一页；关闭裁切时原样复制。

    返回 (裁切后的页列表, 每页的内容列范围)。列范围与空白行用同一套
    tolerance / min_pixels 判定，后面左右裁切与留白直接用它。
    """
    if not settings.enabled:
        cropped = [img.copy() for img in pages]
    else:
        cropped = [
            crop_blank_lines(
                img,
                tolerance=settings.tolerance,
                min_pixels=settings.min_pixels,
                padding=settings.padding,
            )
            for img in pages
        ]

    background = estimate_pages_background(cropped)
    bounds: List[Optional[Tuple[int, int]]] = []
    for img in cropped:
        try:
            bounds.append(
                detect_content_columns(
                    img, settings.tolerance, settings.min_pixels, background
                )
            )
        except Exception:  # noqa: BLE001 - 列检测失败不应影响主流程
            bounds.append(None)
    return cropped, bounds


def export_long_image(
    pages: List[Image.Image],
    settings: StitchSettings,
    background: Tuple[int, int, int],
    output_path: str,
    quality: int = 95,
) -> Tuple[str, Tuple[int, int]]:
    """拼接 → 左右裁切 → 四周留白 → 按输出宽度缩放，返回 (路径, 尺寸)。

    JPEG 默认用 95 质量 + 4:4:4 采样，肉眼几乎无损。
    """
    image = stitch_vertical_variable(pages, list(settings.gaps), settings.align, background)

    if settings.left_crop or settings.right_crop:
        left = max(0, min(settings.left_crop, image.width - 1))
        right = max(left + 1, image.width - max(0, settings.right_crop))
        image = image.crop((left, 0, right, image.height))

    image = add_margins(
        image,
        settings.top_margin,
        settings.bottom_margin,
        background,
        settings.side_pad,
        settings.side_pad,
    )

    if settings.output_width > 0 and settings.output_width != image.width:
        height = max(1, round(image.height * settings.output_width / image.width))
        image = image.resize(
            (settings.output_width, height), Image.LANCZOS, reducing_gap=2.0
        )

    return save_long_image(image, output_path, quality=quality), image.size


# --------------------------------------------------------------------------- #
#  异步执行框架
# --------------------------------------------------------------------------- #
class AsyncRunner:
    """
    单任务后台执行器：同一时刻只允许一个任务在跑。

    任务函数在线程中执行，结束后把结果放入队列；poll() 由定时器在主线程
    驱动，负责取结果并执行回调。Windows 上自动为每个线程做 COM 初始化，
    以便线程中调用 Word 的 COM 接口（docx2pdf / pywin32）。
    """

    _NEED_COM = sys.platform == "win32"

    def __init__(
        self,
        root: tk.Misc,
        on_start: Optional[Callable[[], None]] = None,
        on_finish: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ):
        self._root = root
        self._on_start = on_start
        self._on_finish = on_finish
        self._on_error = on_error
        self._queue: "queue.Queue[Tuple[bool, Any, Optional[BaseException], Optional[Callable]]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(self, func: Callable[[], Any], callback: Optional[Callable[[Any], None]] = None) -> bool:
        """提交任务；已有任务在跑时忽略本次提交并返回 False。"""
        if self.busy:
            return False
        if self._on_start:
            self._on_start()
        self._thread = threading.Thread(
            target=self._worker, args=(func, callback), daemon=True
        )
        self._thread.start()
        return True

    def _worker(self, func, callback) -> None:
        if self._NEED_COM:
            self._com_initialize()
        try:
            ok, value, error = True, func(), None
        except BaseException as exc:  # noqa: BLE001 - 需把任何异常交回主线程
            ok, value, error = False, None, exc
        finally:
            if self._NEED_COM:
                self._com_uninitialize()
        self._queue.put((ok, value, error, callback))

    def poll(self) -> None:
        """在主线程取出已完成的任务结果并执行回调。"""
        while True:
            try:
                ok, value, error, callback = self._queue.get_nowait()
            except queue.Empty:
                return
            if self._on_finish:
                self._on_finish()
            if ok:
                if callback is not None:
                    callback(value)
            elif self._on_error is not None and error is not None:
                self._on_error(error)

    def join(self, timeout: Optional[float] = None) -> None:
        """等待当前任务结束（供测试使用）。"""
        if self._thread is not None:
            self._thread.join(timeout)

    @staticmethod
    def _com_initialize() -> None:
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass

    @staticmethod
    def _com_uninitialize() -> None:
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:
            pass
