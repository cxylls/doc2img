#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc2img —— 文档转长图工具包。

将原先的单文件图形界面按职责拆分为多个模块，依赖方向严格单向，
不存在循环导入：

    config ─┬──────────┬─────────┬──────────┐
            ▼          ▼         ▼          ▼
         models       state     utils    widgets
            │            │        │          │
            │            └───┬────┘          │
            ▼                ▼               ▼
          tasks ◄── panels                  preview
            │                │                  │
            └────────────────┴─────► app ◄──────┘

    第 1 层  config    常量与默认值，无内部依赖
    第 2 层  models    数据类 + 版式几何计算（无 tkinter / PIL）
             settings  settings.ini 默认参数读写
             utils     通用工具函数
    第 3 层  state     Tk 变量容器与文档状态
             widgets   可复用控件与定时器管理
    第 4 层  tasks     后台任务与异步执行框架
             preview   预览按需渲染
    第 5 层  panels    左侧设置面板
    第 6 层  app       主应用，组装以上各层

关键约束：panels 不导入 app，面板所需回调由外部注入，
以此切断界面层与业务层的相互引用。

运行：python doc2img_gui.py
"""

from .app import Doc2ImgApp, main

__version__ = "2.1.0"

__all__ = ["Doc2ImgApp", "main", "__version__"]
