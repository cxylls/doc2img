#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docx 文档 -> 单张长图（自动裁切页首尾空白 + 垂直无缝拼接）

流程：
    1. docx -> PDF（依次尝试 docx2pdf / Microsoft Word COM / LibreOffice）
    2. PDF  -> 逐页渲染为图片（依次尝试 PyMuPDF / pdf2image+poppler）
    3. 每页逐行扫描，裁掉顶部与底部连续的空白行（整行全空白才裁，宽度不变）
    4. 按页序垂直拼接到统一宽度的画布上，页间无多余空白
    5. 保存为一张长图

依赖安装：
    pip install pillow numpy
    # PDF 渲染（二选一，推荐 PyMuPDF，无需额外系统组件）
    pip install PyMuPDF            # 或：pip install pdf2image（还需 poppler）
    # docx 转 PDF（Windows 有 Word 时二选一）
    pip install docx2pdf           # 或：pip install comtypes
    # 无 Word 时可安装 LibreOffice 作为兜底

命令行用法：
    python docx_to_long_image.py input.docx -o long.png --dpi 200
    python docx_to_long_image.py input.docx -o long.png --spacing 8 --align center
    python docx_to_long_image.py                       # 无参数进入交互式模式
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

# 拼接出的长图可能非常大，解除 PIL 默认的安全限制
Image.MAX_IMAGE_PIXELS = None

# JPEG 单边最大像素数
JPEG_MAX_DIM = 65500

DEFAULT_DPI = 200
DEFAULT_TOLERANCE = 12  # 与背景色的通道差值超过该值即视为"有内容"
DEFAULT_MIN_PIXELS = 1  # 一行至少有多少个内容像素才算"有内容行"（过滤噪点）

# 说明：本程序只做"空白行"裁切——一整行都接近背景色才算空白行。
# 不检测也不裁切左右边界，页面宽度始终保持原始宽度。


# --------------------------------------------------------------------------- #
#  第一部分：docx -> PDF
# --------------------------------------------------------------------------- #
def _pdf_ok(pdf_path: str) -> bool:
    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0


def _convert_via_docx2pdf(docx_path: str, pdf_path: str) -> bool:
    try:
        from docx2pdf import convert
    except ImportError:
        return False
    convert(os.path.abspath(docx_path), os.path.abspath(pdf_path))
    return _pdf_ok(pdf_path)


def _convert_via_word_com(docx_path: str, pdf_path: str) -> bool:
    """通过 Microsoft Word（COM）另存为 PDF，支持 comtypes 与 pywin32。"""
    src = os.path.abspath(docx_path)
    dst = os.path.abspath(pdf_path)
    word = doc = None
    backend = None

    try:
        import comtypes.client  # type: ignore

        backend = "comtypes"
        word = comtypes.client.CreateObject("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(src, ReadOnly=True)
        doc.SaveAs(dst, FileFormat=17)  # 17 = wdFormatPDF
    except ImportError:
        try:
            import win32com.client  # type: ignore

            backend = "pywin32"
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(src, ReadOnly=True)
            doc.SaveAs(dst, FileFormat=17)
        except ImportError:
            return False
    finally:
        if doc is not None:
            try:
                doc.Close(SaveChanges=False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        if backend == "comtypes":
            try:
                import comtypes  # type: ignore

                comtypes.CoUninitialize()
            except Exception:
                pass

    return _pdf_ok(pdf_path)


def _find_soffice() -> Optional[str]:
    for name in ("soffice", "libreoffice", "soffice.bin"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _convert_via_libreoffice(docx_path: str, pdf_path: str) -> bool:
    soffice = _find_soffice()
    if not soffice:
        return False

    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    before = set(os.listdir(out_dir))
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir,
         os.path.abspath(docx_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
    )
    produced = os.path.join(
        out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    )
    if os.path.exists(produced):
        if os.path.abspath(produced) != os.path.abspath(pdf_path):
            shutil.move(produced, pdf_path)
        return _pdf_ok(pdf_path)

    # 兜底：取本次新生成的 pdf
    new_files = [f for f in set(os.listdir(out_dir)) - before if f.lower().endswith(".pdf")]
    if new_files:
        shutil.move(os.path.join(out_dir, new_files[0]), pdf_path)
    return _pdf_ok(pdf_path)


def docx_to_pdf(docx_path: str, pdf_path: str) -> str:
    """将 docx 转成 PDF，按可用后端依次尝试。"""
    methods = (
        ("docx2pdf", _convert_via_docx2pdf),
        ("Microsoft Word (COM)", _convert_via_word_com),
        ("LibreOffice", _convert_via_libreoffice),
    )
    errors = []
    for name, func in methods:
        try:
            if func(docx_path, pdf_path):
                print(f"  [OK] docx -> PDF 使用：{name}")
                return pdf_path
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            if _pdf_ok(pdf_path):
                return pdf_path

    raise RuntimeError(
        "无法将文档转换为 PDF。已尝试：\n  - "
        + "\n  - ".join(errors or ["无可用后端"])
        + "\n请安装 Microsoft Word / LibreOffice，或先手动把文档另存为 PDF 后直接输入 PDF。"
    )


# --------------------------------------------------------------------------- #
#  第二部分：PDF -> 逐页图片
# --------------------------------------------------------------------------- #
def _render_with_pymupdf(pdf_path: str, dpi: int) -> List[Image.Image]:
    try:
        import pymupdf as fitz  # type: ignore  # PyMuPDF >= 1.24 推荐写法
    except ImportError:
        try:
            import fitz  # type: ignore  # PyMuPDF < 1.24
        except ImportError:
            raise ImportError("PyMuPDF 未安装")

    images: List[Image.Image] = []
    doc = fitz.open(pdf_path)
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    finally:
        doc.close()
    return images


def _render_with_pdf2image(pdf_path: str, dpi: int, poppler_path: Optional[str]) -> List[Image.Image]:
    from pdf2image import convert_from_path  # type: ignore

    kwargs = {"dpi": dpi}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    return [img.convert("RGB") for img in convert_from_path(pdf_path, **kwargs)]


def pdf_to_images(pdf_path: str, dpi: int = DEFAULT_DPI,
                  poppler_path: Optional[str] = None) -> List[Image.Image]:
    """渲染 PDF 每一页为 PIL 图片。"""
    if poppler_path is None:
        poppler_path = os.environ.get("POPPLER_PATH") or None

    try:
        images = _render_with_pymupdf(pdf_path, dpi)
        print(f"  [OK] PDF -> 图片 使用：PyMuPDF")
        return images
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] PyMuPDF 渲染失败（{exc}），改用 pdf2image")

    try:
        images = _render_with_pdf2image(pdf_path, dpi, poppler_path)
        print("  [OK] PDF -> 图片 使用：pdf2image")
        return images
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"PDF 转图片失败：{exc}\n"
            "请安装 PyMuPDF（pip install PyMuPDF），或安装 pdf2image + poppler 并用 "
            "--poppler-path 指定 poppler 的 bin 目录。"
        ) from exc


# --------------------------------------------------------------------------- #
#  第三部分：空白检测与裁切
# --------------------------------------------------------------------------- #
def estimate_background(arr: np.ndarray) -> np.ndarray:
    """用四条边缘像素的中位数估计页面背景色，兼容非白底/浅色底文档。"""
    edges = np.concatenate(
        [
            arr[0, :, :].reshape(-1, 3),
            arr[-1, :, :].reshape(-1, 3),
            arr[:, 0, :].reshape(-1, 3),
            arr[:, -1, :].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(edges, axis=0)


def detect_content_lines(
    image: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    min_pixels: int = DEFAULT_MIN_PIXELS,
) -> Optional[Tuple[int, int]]:
    """
    逐行扫描，找出首尾"有内容行"的行号。

    仅按整行判定：一整行都接近背景色时算空白行，否则算有内容行。
    不检测左右边界。

    返回 (top, bottom)（bottom 为最后一个内容行的行号，闭区间）；
    整幅图全是空白行时返回 None。

    tolerance: 与背景色的最大通道差值超过该值即视为内容像素（0-255）
    min_pixels: 一行至少 min_pixels 个内容像素才算"有内容行"（过滤噪点与抗锯齿毛边）
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.int16)

    bg = estimate_background(arr)
    deviation = np.abs(arr - bg).max(axis=2)
    mask = deviation > tolerance

    row_hits = mask.sum(axis=1)  # 每一行的内容像素个数
    rows = np.nonzero(row_hits >= min_pixels)[0]
    if rows.size == 0:
        return None

    return int(rows[0]), int(rows[-1])


def estimate_pages_background(images: Sequence[Image.Image]) -> np.ndarray:
    """
    把多张图（通常是各页）四条边缘的像素汇总后估计统一背景色。

    等价于「先拼成长图再估计背景」：逐页估计时，若某页上下边缘就是内容，
    背景会被误判成内容色，空白列就检不出来。
    """
    samples = []
    for image in images:
        width, height = image.size
        strips = (
            image.crop((0, 0, width, 1)),
            image.crop((0, height - 1, width, height)),
            image.crop((0, 0, 1, height)),
            image.crop((width - 1, 0, width, height)),
        )
        samples.extend(
            np.asarray(strip.convert("RGB"), dtype=np.int16).reshape(-1, 3)
            for strip in strips
        )
    if not samples:
        return np.array([255, 255, 255], dtype=np.int16)
    return np.median(np.concatenate(samples, axis=0), axis=0)


def detect_content_columns(
    image: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    background: Optional[np.ndarray] = None,
) -> Optional[Tuple[int, int]]:
    """
    逐列扫描，找出首尾"有内容列"的列号。

    判定方式与 detect_content_lines 完全一致，只是把行换成列：
    一整列都接近背景色时算空白列，否则算有内容列。

    background: 可传入整份文档统一的背景色（见 estimate_pages_background），
    不传则用本图四条边缘估计。

    返回 (left, right)（right 为最后一个内容列的列号，闭区间）；
    整幅图全是空白列时返回 None。
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.int16)

    bg = (
        estimate_background(arr)
        if background is None
        else np.asarray(background, dtype=np.int16)
    )
    deviation = np.abs(arr - bg).max(axis=2)
    mask = deviation > tolerance

    col_hits = mask.sum(axis=0)  # 每一列的内容像素个数
    cols = np.nonzero(col_hits >= min_pixels)[0]
    if cols.size == 0:
        return None

    return int(cols[0]), int(cols[-1])


def crop_blank_lines(
    image: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    padding: int = 0,
) -> Image.Image:
    """
    裁掉图片顶部与底部连续的空白行，宽度保持不变，内部空白行全部保留。

    整幅图全为空白行时原样返回（不再整页丢弃，避免出现空档）。

    padding: 裁切后上下额外保留的原始留白行数；传负数可再多裁几行。
    """
    bounds = detect_content_lines(image, tolerance, min_pixels)
    if bounds is None:
        return image

    top, bottom = bounds
    top = max(0, top - padding)
    bottom = min(image.height - 1, bottom + padding)

    return image.crop((0, top, image.width, bottom + 1))


# --------------------------------------------------------------------------- #
#  第四部分：垂直拼接
# --------------------------------------------------------------------------- #
def stitch_vertical_variable(
    images: Sequence[Image.Image],
    gaps: Sequence[int],
    align: str = "center",
    background: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """
    把多张图片垂直拼接为一张长图，每一段间隙可单独指定。

    gaps[i] 表示第 i 张与第 i+1 张之间的间隙像素数，长度应为 len(images)-1；
    长度不足时按 0 补齐，多出的部分忽略。
    """
    if not images:
        raise ValueError("没有可拼接的图片")

    images = [img.convert("RGB") for img in images]
    n_gaps = len(images) - 1
    gaps = [max(0, int(g)) for g in list(gaps)[:n_gaps]] + [0] * max(0, n_gaps - len(gaps))

    max_width = max(img.width for img in images)
    total_height = sum(img.height for img in images) + sum(gaps)

    canvas = Image.new("RGB", (max_width, total_height), background)

    y = 0
    for i, img in enumerate(images):
        if align == "left":
            x = 0
        elif align == "right":
            x = max_width - img.width
        else:
            x = (max_width - img.width) // 2
        canvas.paste(img, (x, y))
        y += img.height + (gaps[i] if i < n_gaps else 0)

    return canvas


def stitch_vertical(
    images: Sequence[Image.Image],
    spacing: int = 0,
    align: str = "center",
    background: Tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """把多张图片垂直拼接为一张长图，页与页之间统一保留 spacing 像素间隙。"""
    return stitch_vertical_variable(
        images, [max(0, int(spacing))] * (len(images) - 1), align, background
    )


def add_margins(
    image: Image.Image,
    top: int,
    bottom: int,
    background: Tuple[int, int, int],
    left: int = 0,
    right: int = 0,
) -> Image.Image:
    """给长图整体加四周留白。"""
    top, bottom = max(0, int(top)), max(0, int(bottom))
    left, right = max(0, int(left)), max(0, int(right))
    if top == bottom == left == right == 0:
        return image
    canvas = Image.new(
        "RGB",
        (image.width + left + right, image.height + top + bottom),
        background,
    )
    canvas.paste(image, (left, top))
    return canvas


def save_long_image(image: Image.Image, output_path: str, quality: int = 92) -> str:
    """保存长图，自动处理 JPEG 尺寸上限。"""
    ext = os.path.splitext(output_path)[1].lower()
    width, height = image.size

    if ext in (".jpg", ".jpeg"):
        if max(width, height) > JPEG_MAX_DIM:
            output_path = os.path.splitext(output_path)[0] + ".png"
            ext = ".png"
            print(f"  [!] 图片尺寸 {width}x{height} 超出 JPEG 上限 {JPEG_MAX_DIM}，自动改为 PNG 保存")
        else:
            image.save(output_path, "JPEG", quality=quality, optimize=True, subsampling=0)
            return output_path

    if ext not in (".png", ".bmp", ".tif", ".tiff", ".webp"):
        output_path = os.path.splitext(output_path)[0] + ".png"

    if max(width, height) > JPEG_MAX_DIM:
        print(f"  [i] 长图高度 {height}px 较大，部分看图软件/浏览器可能无法正常显示")

    image.save(output_path)
    return output_path


# --------------------------------------------------------------------------- #
#  主流程
# --------------------------------------------------------------------------- #
def docx_to_long_image(
    docx_path: str,
    output_path: Optional[str] = None,
    dpi: int = DEFAULT_DPI,
    tolerance: int = DEFAULT_TOLERANCE,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    spacing: int = 0,
    align: str = "center",
    page_padding: int = 0,
    top_margin: int = 0,
    bottom_margin: int = 0,
    save_pages_dir: Optional[str] = None,
    poppler_path: Optional[str] = None,
    quality: int = 92,
) -> str:
    """把 docx（或 pdf）转成一张裁掉页首尾空白行并垂直拼接的长图，返回输出路径。"""
    docx_path = os.path.abspath(os.path.expanduser(docx_path))
    if not os.path.exists(docx_path):
        raise FileNotFoundError(f"输入文件不存在：{docx_path}")

    if output_path is None:
        output_path = os.path.splitext(docx_path)[0] + "_long.png"
    output_path = os.path.abspath(os.path.expanduser(output_path))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    print(f"输入文件：{docx_path}")
    print(f"输出文件：{output_path}")
    print(f"渲染 DPI：{dpi}\n")

    is_pdf = docx_path.lower().endswith(".pdf")
    temp_dir = tempfile.mkdtemp(prefix="docx2long_")
    try:
        # 1) docx -> PDF
        if is_pdf:
            pdf_path = docx_path
        else:
            print("[1/4] 转换文档为 PDF ...")
            pdf_path = os.path.join(temp_dir, "document.pdf")
            docx_to_pdf(docx_path, pdf_path)

        # 2) PDF -> 逐页图片
        print("[2/4] 渲染每一页为图片 ...")
        pages = pdf_to_images(pdf_path, dpi=dpi, poppler_path=poppler_path)
        if not pages:
            raise RuntimeError("未渲染出任何页面，文档可能为空")
        print(f"  共 {len(pages)} 页")

        # 3) 裁切首尾空白行
        print("[3/4] 检测并裁切每页顶部/底部空白行 ...")
        cropped: List[Image.Image] = []
        for index, page in enumerate(pages, start=1):
            result = crop_blank_lines(
                page,
                tolerance=tolerance,
                min_pixels=min_pixels,
                padding=page_padding,
            )
            cut = page.height - result.height
            cropped.append(result)
            print(
                f"  第 {index:>3} 页：{page.width}x{page.height} -> "
                f"{result.width}x{result.height}（裁掉首尾共 {cut} 行）"
            )

        if save_pages_dir:
            os.makedirs(save_pages_dir, exist_ok=True)
            for index, page in enumerate(cropped, start=1):
                page.save(os.path.join(save_pages_dir, f"page_{index:03d}.png"))
            print(f"  中间页图已保存到：{save_pages_dir}")

        # 4) 拼接
        print("[4/4] 垂直拼接 ...")
        first_arr = np.asarray(cropped[0].convert("RGB"), dtype=np.int16)
        background = tuple(int(v) for v in estimate_background(first_arr))

        long_image = stitch_vertical(cropped, spacing=spacing, align=align, background=background)
        long_image = add_margins(long_image, top_margin, bottom_margin, background)

        output_path = save_long_image(long_image, output_path, quality=quality)
        print(f"\n完成！共 {len(cropped)} 页，最终长图：{long_image.width} x {long_image.height}")
        print(f"已保存：{output_path}")
        return output_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
#  命令行 / 交互
# --------------------------------------------------------------------------- #
def _ask_int(prompt: str, default: int) -> int:
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  输入无效，使用默认值 {default}")
        return default


def interactive() -> int:
    print("=== docx 长图生成器 ===")
    src = input("请输入 docx（或 pdf）文件路径: ").strip().strip('"')
    if not src:
        print("路径不能为空")
        return 1

    out = input("请输入输出图片路径（留空自动生成）: ").strip().strip('"') or None
    dpi = _ask_int("渲染 DPI（默认 200）: ", 200)
    spacing = _ask_int("页间留白像素（默认 0，即无缝）: ", 0)
    align = input("对齐方式 left/center/right（默认 center）: ").strip().lower() or "center"

    try:
        docx_to_long_image(src, out, dpi=dpi, spacing=spacing, align=align)
    except Exception as exc:  # noqa: BLE001
        print(f"\n失败：{exc}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把 docx 文档每一页渲染成图片，裁掉首尾空白行后垂直拼接为一张长图",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="输入 .docx 文件路径（也支持 .pdf）")
    parser.add_argument("-o", "--output", help="输出长图路径（默认与输入同目录，*_long.png）")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="渲染分辨率")
    parser.add_argument(
        "--tolerance", type=int, default=DEFAULT_TOLERANCE,
        help="空白判定容差：与背景色的通道差值超过此值算作内容（0-255，越小越严格）",
    )
    parser.add_argument(
        "--min-pixels", type=int, default=DEFAULT_MIN_PIXELS,
        help="一行最少有多少个内容像素才算「有内容行」（过滤噪点）",
    )
    parser.add_argument("--spacing", type=int, default=0, help="页与页之间的留白像素数（默认 0，无缝）")
    parser.add_argument("--align", choices=["left", "center", "right"], default="center",
                        help="页面宽度不一致时的对齐方式")
    parser.add_argument("--page-padding", type=int, default=0,
                        help="裁切后每页上下额外保留的原始留白行数（负数表示多裁几行）")
    parser.add_argument("--top-margin", type=int, default=0, help="长图顶部留白像素数")
    parser.add_argument("--bottom-margin", type=int, default=0, help="长图底部留白像素数")
    parser.add_argument("--save-pages", metavar="DIR", help="同时把裁切后的每一页图片保存到该目录")
    parser.add_argument("--poppler-path", help="poppler 的 bin 目录（使用 pdf2image 时需要）")
    parser.add_argument("--quality", type=int, default=92, help="JPEG 保存质量（1-95）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if len(sys.argv) == 1 and not argv:
        return interactive()

    args = build_parser().parse_args(argv)
    if not args.input:
        print("错误：请提供输入文件路径（或不带参数运行进入交互模式）")
        return 1

    try:
        docx_to_long_image(
            docx_path=args.input,
            output_path=args.output,
            dpi=args.dpi,
            tolerance=args.tolerance,
            min_pixels=args.min_pixels,
            spacing=args.spacing,
            align=args.align,
            page_padding=args.page_padding,
            top_margin=args.top_margin,
            bottom_margin=args.bottom_margin,
            save_pages_dir=args.save_pages,
            poppler_path=args.poppler_path,
            quality=args.quality,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
