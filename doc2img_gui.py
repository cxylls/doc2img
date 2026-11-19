#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图形界面入口脚本（供 PyInstaller 打包使用）。

包内用的是相对导入，不能直接把 `doc2img/__main__.py` 当脚本运行，
所以单独放一个入口。
"""

import sys

from doc2img.app import main

if __name__ == "__main__":
    sys.exit(main())
