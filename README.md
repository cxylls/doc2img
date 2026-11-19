# 文档转长图

把 `.doc` / `.docx` / `.pdf` 每一页渲染成图片，自动裁掉每页首尾空白行，再垂直拼接为一张长图。

## 安装依赖

需要 Python 3.9 及以上（Windows 的 CPython 安装包通常已自带 `tkinter`）。
在项目根目录执行：

```bash
python -m pip install --upgrade pip
python -m pip install pillow numpy PyMuPDF
```

- `pillow`、`numpy`：**必需**，负责图像处理与像素计算。
- `PyMuPDF`：**推荐**，负责把 PDF 渲染成图片；装好后即可直接输入 `.pdf`。

其余依赖按输入文档类型按需安装：

| 场景 | 安装方式 | 说明 |
|---|---|---|
| 输入 `.doc` / `.docx` | `python -m pip install docx2pdf` | 需要本机安装 Microsoft Word |
| 输入 `.doc` / `.docx`，没有 Word | 安装 LibreOffice | 作为文档转 PDF 的兜底方案 |
| 不用 PyMuPDF 渲染 PDF | `python -m pip install pdf2image`，另装 poppler | 用 `--poppler-path` 指向 poppler 的 `bin` 目录（仅命令行工具支持） |
| 打包为 exe | `python -m pip install pyinstaller` | 见下方「打包为 exe」 |

也可以先把 Word 文档另存为 PDF 再输入，这样就不需要 `docx2pdf` / Word / LibreOffice。

建议在项目根目录创建虚拟环境后再安装，避免污染全局环境：

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell / CMD
python -m pip install pillow numpy PyMuPDF
```

## 运行

```bash
python doc2img_gui.py          # 图形界面
```

界面里点「打开文件」选好文档即自动渲染、裁切并生成预览，不需要再点载入。

处理完点「导出图片」：弹窗默认落在源文档目录，文件名自动取源文档名（不加后缀），
默认存为 JPG（质量 95、4:4:4 采样，肉眼几乎无损），也可以改成 PNG。

## 打包为 exe

```bash
pip install pyinstaller
python build_exe.py            # 目录版（默认，启动最快）
python build_exe.py --onefile  # 单文件版，便于分发
```

默认按最大性能打包：目录版 + 关闭 UPX 压缩 + 字节码优化（`--optimize 2`）+ 排除用不到的
重型库。产物在 `dist/doc2img_gui/`，`settings.ini` 会一起放在 exe 旁边；分发时整个目录拷走即可。

命令行工具（无界面，适合批量处理）：

```bash
python docx_to_long_image.py 文档.docx -o 长图.png --dpi 200
python docx_to_long_image.py 文档.docx -o 长图.png --spacing 8 --align center
```

## 默认参数

启动时读取项目根目录的 `settings.ini`（不存在会按默认值自动生成），改完重启生效。
界面里仍可临时修改这些值，配置文件只决定每次启动时的初始值。

```ini
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
```

`容差` / `最小像素` / `额外保留行数` 不再显示在界面上，固定使用核心模块的默认判定。

## 目录结构

```
doc2img/
├── build_exe.py              打包成 exe（PyInstaller）
├── docx_to_long_image.py     核心模块 + 命令行工具（不依赖 GUI）
├── doc2img_gui.py            exe 入口脚本
├── settings.ini              默认参数（中文键名，改完重启生效）
└── doc2img/                  图形界面包
    ├── __init__.py           包说明
    ├── __main__.py           包入口
    │
    │   ── 第 1 层：无内部依赖 ──
    ├── config.py             常量、默认值、取值范围、防抖延时
    │
    │   ── 第 2 层：纯逻辑，无 tkinter / PIL ──
    ├── models.py             数据类 + 版式几何计算
    ├── settings.py           settings.ini 默认参数读写
    ├── utils.py              DPI 感知、安全取值、路径推导
    │
    │   ── 第 3 层：GUI 基础设施 ──
    ├── state.py              Tk 变量容器 + 文档状态
    ├── widgets.py            可复用控件 + 定时器管理
    │
    │   ── 第 4 层：业务能力 ──
    ├── tasks.py              后台任务与异步执行框架
    ├── preview.py            预览按需渲染（只画可视区）
    │
    │   ── 第 5 层：界面组装 ──
    ├── panels.py             左侧设置面板
    │
    │   ── 第 6 层：总装 ──
    └── app.py                主应用 Doc2ImgApp
```

## 模块职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `config.py` | 全部常量、默认值、控件取值范围、防抖延时 | 无 |
| `models.py` | `CropSettings` / `StitchSettings` / `PageLayout` 数据类；`resolve_gaps`、`build_layout`、`compute_scale` 纯函数 | `config` |
| `utils.py` | `enable_dpi_awareness`（高 DPI 清晰）、`safe_int`（安全读 Tk 变量）、`clear_children` | 无 |
| `settings.py` | 读取项目根目录 `settings.ini` 的默认参数；文件缺失时自动生成模板 | `config` |
| `state.py` | `UiVariables`（全部 Tk 变量）、`DocumentState`（页面数据、临时 PDF 生命周期） | `config` |
| `widgets.py` | `ScrollableFrame` 滚动容器、`JobTracker` 定时器管理、Spinbox/Combobox 组合控件 | 无 |
| `tasks.py` | `AsyncRunner` 单任务后台执行器（自动 COM 初始化）+ 载入/裁切/导出任务函数 | `models` |
| `preview.py` | `PreviewRenderer`：按需渲染视口附近一段，不整张渲染 | `config`、`models` |
| `panels.py` | `ControlPanel`：裁切 / 左右空白 / 页间空白 / 拼接 / 导出五组面板 | `config`、`utils`、`widgets` |
| `app.py` | `Doc2ImgApp`：组装各层，处理用户操作与任务调度 | 全部 |

## 依赖方向

严格单向，无循环导入：

```
config ─┬──────────┬─────────┬──────────┐
        ▼          ▼         ▼          ▼
     models       state     utils    widgets
        │            │        │          │
        │            └───┬────┘          │
        ▼                ▼               ▼
      tasks ◄── panels                 preview
        │                │                  │
        └────────────────┴─────► app ◄──────┘
```

关键约束：**`panels` 不导入 `app`**。面板所需回调在构造时注入，
以此切断界面层与业务层的相互引用。

## 设计要点

这几处是有意为之、改动前需要理解的实现约束：

- **`enable_dpi_awareness()` 必须在 `tk.Tk()` 之前调用**，之后调用无效。
  未开启时进程被告知 96 DPI，在 150% 缩放的屏幕上界面会整体发虚。
- **预览只渲染视口附近一段**（上下各 `BAND_MARGIN` 余量），不整张渲染。
  因此缩放不受成品高度限制，内存与渲染量只与视口有关、与页数无关。
- **渲染会修改 `scrollregion`，进而触发滚动回调，回调又调度渲染**；
  用 `band_key()` 视口指纹比对打断这个环路，避免空转。
- **Tk 变量只能在主线程读取**：`tasks.py` 的任务函数不碰任何 Tk 变量，
  需要的值由调用方在主线程取好后以参数传入。
- **页间空白两种模式共用同一份持久化数值**：只切换模式不会丢数据，
  只有在统一模式下主动改值才视为「全部设为该值」并写回每一段。
- **预览左侧栏的逐段输入框与面板输入框绑定同一个 `IntVar`**，两边因此天然
  双向同步；页数变化重建逐段行后必须调用 `preview.reset_gap_widgets()`，
  丢弃仍绑着旧变量的控件。
- **左右空白在裁完空白行之后处理**：列检测与空白行共用同一份 tolerance /
  min_pixels，但背景色按整份文档的四边像素统一估计（逐页估计会把内容色
  当成背景，空白列就检不出来）。裁切/留白只平移版式盒子，预览与导出走
  同一套计算；四周留白和页间间隔都按**缩放前**像素填，导出缩放到目标
  宽度时整体等比变化。
- **默认参数在 `_build_ui()` 之后、`_attach_traces()` 之前写入**：此时还没有
  回调，不会因此触发多余的裁切/预览计算。
- **两种模式面板共用一个 grid 容器**。不能用 `pack_forget` 来回打包：
  重新 `pack` 会追加到末尾导致顺序错乱，`pack(before=...)` 又要求参照
  物是同级控件。
