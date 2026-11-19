#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部默认参数（项目根目录的 settings.ini）。

配置文件用中文键名，改完重启程序生效；文件不存在时会按内置默认值
自动生成，方便用户直接打开编辑。

    [默认值]
    DPI = 200
    顶部留白 = 100
    底部留白 = 100
    图片间隔 = 150
    左右留白 = 100
    输出宽度 = 1080
"""

import configparser
import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from .config import DPI_RANGE, GAP_RANGE, MARGIN_RANGE, OUTPUT_WIDTH_RANGE

INI_FILENAME = "settings.ini"
SECTION = "默认值"


def _base_dir() -> str:
    """打包成 exe 后，配置文件放在 exe 旁边而不是临时解压目录里。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROJECT_ROOT = _base_dir()

CONFIG_TEMPLATE = """\
# 文档转长图的默认参数（单位：像素）
# 改完保存，重新启动程序生效；删除本文件会按下面的值重新生成。

[默认值]
# 文档渲染清晰度（DPI），越大越清晰、处理越慢
DPI = 200
# 长图顶部留白（缩放前的像素）
顶部留白 = 100
# 长图底部留白（缩放前的像素）
底部留白 = 100
# 相邻两张图片之间的空白（缩放前的像素）
图片间隔 = 150
# 长图左右两侧各留的空白（缩放前的像素）
左右留白 = 100
# 成品宽度；0 表示保持原始宽度
输出宽度 = 1080
"""


@dataclass(frozen=True)
class Defaults:
    """启动时套用的默认参数。"""

    dpi: int = 200
    top_margin: int = 100
    bottom_margin: int = 100
    gap: int = 150
    side_margin: int = 100
    output_width: int = 1080


FALLBACK = Defaults()


def config_path() -> str:
    """配置文件固定放在项目根目录。"""
    return os.path.join(PROJECT_ROOT, INI_FILENAME)


def load_defaults(path: Optional[str] = None) -> Defaults:
    """读取 settings.ini；缺失、损坏或取值非法时退回内置默认值。"""
    path = path or config_path()

    parser = configparser.ConfigParser()
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error):
        _write_template(path)
        return FALLBACK

    section = parser[SECTION] if parser.has_section(SECTION) else {}
    return Defaults(
        dpi=_read_int(section, "DPI", FALLBACK.dpi, DPI_RANGE),
        top_margin=_read_int(section, "顶部留白", FALLBACK.top_margin, MARGIN_RANGE),
        bottom_margin=_read_int(section, "底部留白", FALLBACK.bottom_margin, MARGIN_RANGE),
        gap=_read_int(section, "图片间隔", FALLBACK.gap, GAP_RANGE),
        side_margin=_read_int(section, "左右留白", FALLBACK.side_margin, MARGIN_RANGE),
        output_width=_read_int(
            section, "输出宽度", FALLBACK.output_width, OUTPUT_WIDTH_RANGE
        ),
    )


def _read_int(section, key: str, default: int, bounds: Tuple[int, int]) -> int:
    """读一个整数并夹在取值范围内；缺失或不是数字时用默认值。"""
    try:
        raw = section[key]
    except KeyError:
        return default

    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(bounds[0], min(bounds[1], value))


def _write_template(path: str) -> None:
    """首次运行时生成一份带注释的配置文件。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(CONFIG_TEMPLATE)
    except OSError:
        pass
