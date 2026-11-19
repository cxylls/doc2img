#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把图形界面打包成 Windows exe（基于 PyInstaller），默认按最大性能打包。

默认生成「目录版 + 不压缩 + 字节码优化」：
    * 目录版启动最快（单文件版每次运行都要先解压到临时目录）
    * 关闭 UPX，避免解压/杀毒扫描拖慢启动
    * --optimize 2 去掉断言与文档字符串，减小体积、略快
    * 排除一批用不到的重型库

用法：
    pip install pyinstaller
    python build_exe.py              # 目录版（推荐），输出 dist/doc2img_gui/
    python build_exe.py --onefile    # 单文件版，便于分发但启动慢
    python build_exe.py --console    # 保留控制台窗口，便于查看报错
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence

ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(ROOT, "doc2img_gui.py")
APP_NAME = "doc2img_gui"

# 运行期才导入（或由可选依赖导入）的模块，PyInstaller 静态分析看不到
HIDDEN_IMPORTS = (
    "pymupdf",
    "fitz",
    "docx2pdf",
    "comtypes.client",
    "win32com.client",
    "pythoncom",
    "pdf2image",
    "PIL._tkinter_finder",
)

# 本项目用不到的重型库，排除后体积更小、扫描更快
EXCLUDES = (
    "matplotlib",
    "scipy",
    "pandas",
    "sklearn",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "torch",
    "tensorflow",
)


def build(onefile: bool, console: bool, icon: Optional[str]) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("需要先安装 PyInstaller：\n    pip install pyinstaller")
        return 2

    dist_dir = os.path.join(ROOT, "dist")
    work_dir = os.path.join(ROOT, "build")

    command: List[str] = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--specpath", work_dir,
        "--paths", ROOT,
        "--windowed" if not console else "--console",
        "--noupx",              # 不压缩，启动更快
        "--optimize", "2",      # 字节码优化，体积更小
    ]
    if onefile:
        command.append("--onefile")

    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    if icon:
        command += ["--icon", os.path.abspath(icon)]
    command.append(ENTRY)

    print("打包中（目录版通常 1-3 分钟）...")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("打包失败，请检查上面的输出。")
        return result.returncode

    app_dir = dist_dir if onefile else os.path.join(dist_dir, APP_NAME)
    exe_path = os.path.join(app_dir, APP_NAME + ".exe")

    # settings.ini 放在 exe 旁边；程序启动时也会在缺失时自动生成
    settings_src = os.path.join(ROOT, "settings.ini")
    settings_dst = os.path.join(app_dir, "settings.ini")
    if os.path.exists(settings_src):
        shutil.copy2(settings_src, settings_dst)

    print(f"\n打包完成：{exe_path}")
    print(f"配置文件：{settings_dst}")
    print(f"分发时整个目录一起拷贝：{app_dir}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 doc2img_gui 打包成 exe（默认按最大性能：目录版 + 不压缩）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--onefile", action="store_true",
                        help="打成单文件（启动较慢，便于分发）")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    parser.add_argument("--icon", help="图标 .ico 路径；默认使用根目录的 icon.ico（若存在）")
    args = parser.parse_args(argv)

    icon = args.icon
    if not icon:
        default_icon = os.path.join(ROOT, "icon.ico")
        icon = default_icon if os.path.exists(default_icon) else None

    return build(onefile=args.onefile, console=args.console, icon=icon)


if __name__ == "__main__":
    raise SystemExit(main())
