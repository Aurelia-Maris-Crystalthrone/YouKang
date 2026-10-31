"""Web Demo 交付打包：把 Web Demo 及其运行期依赖打成"队友拿到就能跑"的交付包。

用法：
    python tools/package_web_demo.py --out <交付目录> [--zip]

产物：
    1. 交付目录（start.bat / start.ps1 / requirements.txt / README.md /
       DEMO_SCRIPT.md / app/ / samples/ / data/ / uploads/）；
    2. --zip 时在项目根生成 YouKang-WebDemo-v0.1.zip；
    3. 项目根 .gitignore 幂等追加交付产物忽略条目。

退出码：0 = 成功（含样例图缺失等软警告场景）；
        2 = 输入/前置类错误（前置产物缺失、交付目录与源码目录重叠）；
        3 = 写盘类错误（拷贝 IO / zip 写入或自校验失败）。

设计要点（为什么这么写）：
    * 本脚本是纯构建期工具，零业务逻辑、零第三方依赖（仅标准库）；
    * 前置产物（指令 A prescribe_prompt / 指令 F sqlite_store / 指令 G web_demo）
      缺失时"宁可硬失败也不发残缺包"——一个缺了 server.py 的离线包毫无意义，
      所以校验先于一切写盘动作（无半成品）；
    * 样例图走"软警告"口径：没有样例图 Demo 照样能跑（用户自传图片），
      两套口径相反是刻意的（spec 5.1 / 5.3）。
"""
from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterator, NamedTuple

# ============================================================
# 一、常量区：全部"口径"的单一事实来源
# ============================================================


class PackageItem(NamedTuple):
    """打包清单条目：相对路径 + 条目类型 + 来源任务名。

    provider 字段是"前置任务提示"的单一数据来源——硬校验报错时
    逐条指名谁没落地，让用户一轮看全要补哪些前置任务（spec 5.1.1-3）。
    """

    rel_path: str
    kind: str  # "file" = 单文件 copy2；"dir" = 整目录受控遍历拷贝
    provider: str


# 17 项打包清单（spec 6.2 唯一口径）：agent 6 + prescription 6 + web_demo 3 + 顶层 2。
# 清单外一律不拷（demo_offline.py / eval_vision.py / tests/ / tools/ 等均为交付无关）。
PACKAGE_ITEMS: tuple[PackageItem, ...] = (
    # agent 组
    PackageItem("agent/orchestrator.py", "file", "本仓库存量"),
    PackageItem("agent/vision_client.py", "file", "本仓库存量"),
    PackageItem("agent/vision_prompt.py", "file", "本仓库存量"),
    PackageItem("agent/discriminate.py", "file", "本仓库存量"),
    PackageItem("agent/questions.json", "file", "本仓库存量"),
    PackageItem("agent/prescribe_prompt.py", "file", "前置任务『指令A · 处方文案生成组件』"),
    # prescription 组
    PackageItem("prescription/rule_engine.py", "file", "本仓库存量"),
    PackageItem("prescription/guardrail.py", "file", "本仓库存量"),
    PackageItem("prescription/load_from_db.py", "file", "本仓库存量"),
    PackageItem("prescription/sqlite_store.py", "file", "前置任务『指令C/F · SQLite 处方库』"),
    PackageItem("prescription/schema.sql", "file", "本仓库存量"),
    PackageItem("prescription/seed_data.sql", "file", "本仓库存量"),
    # web_demo 组
    PackageItem("web_demo/server.py", "file", "前置任务『指令G · Web Demo 对话界面』"),
    PackageItem("web_demo/offline_client.py", "file", "前置任务『指令G · Web Demo 对话界面』"),
    PackageItem("web_demo/static", "dir", "前置任务『指令G · Web Demo 对话界面』"),
    # 顶层组
    PackageItem("expert_knowledge.py", "file", "本仓库存量"),
    PackageItem("labelmap.py", "file", "本仓库存量"),
)


class SampleSpec(NamedTuple):
    """样例图挑选规格：文件名前缀 + 预期结论口径。"""

    prefix: str
    label: str
    label_cn: str
    highlights: str


# 五前缀样例图映射（spec 6.4）。
# 口径同步义务：label 取值与 labelmap.py 的 CLASS_NAMES ∪ {HEALTHY_LABEL} 一致，
# label_cn 与 agent/vision_prompt.py 的 CLASS_CN 一致（healthy → "健康"）。
# 刻意用静态常量而**不**运行时 import 这两个模块——打包脚本必须在源码树
# 残缺时也能启动并给出"缺文件报错"，运行时 import 会把报错劣化为
# ImportError，破坏 5.1 的报错契约（design 决策 D9）。
SAMPLE_IMAGE_SPECS: tuple[SampleSpec, ...] = (
    SampleSpec(
        prefix="canker",
        label="canker",
        label_cn="溃疡病",
        highlights="演示看点：处方卡片可用/禁用两栏与中文拒绝理由（配伍禁忌等规则触发）。",
    ),
    SampleSpec(
        prefix="greening",
        label="greening",
        label_cn="黄龙病（柑橘黄龙病，检疫性病害）",
        highlights="演示看点：触发检疫上报提示与无药可治四要点（上报/挖除/防木虱/无病苗木），处方为空。",
    ),
    SampleSpec(
        prefix="red_spider_mite",
        label="red_spider_mite",
        label_cn="红蜘蛛（柑橘全爪螨）",
        highlights="演示看点：杀螨类处方与抗药性轮换拒绝提示。",
    ),
    SampleSpec(
        prefix="anthracnose",
        label="anthracnose",
        label_cn="炭疽病",
        highlights="演示看点：咪鲜胺等杀菌剂处方与安全间隔期说明。",
    ),
    SampleSpec(
        prefix="__negative___healthy",
        label="healthy",
        label_cn="健康",
        highlights="演示看点：无处方、无用药方案，仅健康结论与养护建议。",
    ),
)

# requirements 只列 Demo 运行/测试真正用到的 5 个包（spec 5.4.1-4）：
# 不钉版本（镜像装最新兼容版）、无注释行、无空行。
REQUIREMENTS_LINES: tuple[str, ...] = (
    "fastapi",
    "uvicorn[standard]",
    "python-multipart",
    "requests",
    "pytest",
)

SERVER_PORT: int = 7860
PIP_MIRROR: str = "https://mirrors.aliyun.com/pypi/simple/"
ZIP_FILENAME: str = "YouKang-WebDemo-v0.1.zip"
ZIP_SIZE_WARN_BYTES: int = 50 * 1024 * 1024  # 50MB 红线：超限只警告不拦截（白名单机制下不可达，留防御性观测）

# .gitignore 追加条目（spec 6.7）：交付目录整体 / zip / 启动日志 / 源码侧运行时产物。
GITIGNORE_SECTION_TITLE = "# ---------- Web Demo 交付产物（打包生成，不入库） ----------"
GITIGNORE_APPEND_LINES: tuple[str, ...] = (
    "web-demo/",
    ZIP_FILENAME,
    "运行日志.txt",
    "web_demo/data/",
    "web_demo/uploads/",
)

# 排除规则参数（spec 6.3）：拷贝与 zip 共用（design 决策 D5——单点维护，
# 改一处两个消费者同步生效）。
EXCLUDE_DIR_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".pytest_cache", ".git", ".idea", ".vscode", "node_modules"}
)
EXCLUDE_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.jsonl",
    "eval_*.json",
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*secret*",
    "*credential*",
    "mcp_settings.json",
    "*.pt",
    "*.pth",
    "*.onnx",
    "*.ms",
)


class MissingItem(NamedTuple):
    """硬校验产出：缺失文件的相对路径 + 来源任务提示。"""

    rel_path: str
    provider: str


class SamplePickResult(NamedTuple):
    """样例图挑选结果：命中映射（前缀 → 源文件）+ 未命中前缀清单。"""

    picked: dict[str, Path]
    missing: tuple[str, ...]


class ZipReport(NamedTuple):
    """zip 产物报告：路径 / 文件总数 / 前 20 文件名（截断）/ 体积字节。"""

    zip_path: Path
    file_count: int
    first_files: tuple[str, ...]
    size_bytes: int


class MissingPrerequisiteError(Exception):
    """前置产物缺失：消息为全部缺失项的中文清单 + 修复指引（spec 5.1.1-3）。"""


# ============================================================
# 二、校验区：前置产物硬校验（缺文件报错退出）
# ============================================================


def validate_prerequisites(src_root: Path) -> list[MissingItem]:
    """对 17 项清单逐项 exists 检查，一次性收集全部缺失项。

    刻意不做 fail-fast（design 决策 D2）：当前实况同时缺 5 项，
    遇到第一个就停会逼用户跑多次才能看全要补哪些前置。
    零写盘副作用——校验必须先于一切写盘动作（spec 5.1.1-4 半成品清理规则）。
    """
    missing: list[MissingItem] = []
    for item in PACKAGE_ITEMS:
        path = src_root / item.rel_path
        ok = path.is_dir() if item.kind == "dir" else path.is_file()
        if not ok:
            missing.append(MissingItem(rel_path=item.rel_path, provider=item.provider))
    return missing


def format_missing(missing: list[MissingItem]) -> str:
    """把缺失清单渲染为中文报错文本（异常消息与 CLI 输出共用一份口径）。"""
    lines = ["以下前置产物缺失，打包需要的文件不存在："]
    lines.extend(f"  - {m.rel_path} —— {m.provider}" for m in missing)
    lines.append(
        "修复指引：请先完成对应前置任务的实现"
        "（指令A 处方文案生成 → 指令C/F SQLite 处方库 → 指令G Web Demo 对话界面），再执行打包。"
    )
    return "\n".join(lines)


# ============================================================
# 三、拷贝区：排除谓词单点 + 白名单拷贝 + 幂等重建与重叠防护
# ============================================================


def is_excluded(rel_path: PurePosixPath) -> bool:
    """排除谓词：目录名集合 ∪ 文件通配模式（含密钥/权重类），spec 6.3 的唯一载体。

    对路径的**每一段**都做模式匹配（不止最后一段）——密钥红线宁可误杀：
    secret_dir/x.py 这类路径同样不得进交付包。路径统一小写后匹配，
    保证跨平台行为一致（fnmatch 在 Linux 上大小写敏感）。
    """
    parts = rel_path.parts
    if not parts:
        return False
    for part in parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
        lowered = part.lower()
        for pattern in EXCLUDE_FILE_PATTERNS:
            if fnmatch.fnmatch(lowered, pattern):
                return True
    return False


def iter_included_files(root: Path) -> Iterator[Path]:
    """受控遍历生成器：yield root 下未被排除规则命中的全部文件。

    static/ 整目录拷贝与 zip 打包共用本遍历器（design 决策 D5）。
    排序遍历保证产物顺序确定（可重复构建，spec 4.2-2）。
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = PurePosixPath(path.relative_to(root).as_posix())
        if is_excluded(rel):
            continue
        yield path


def copy_package_files(src_root: Path, out_dir: Path) -> None:
    """按白名单把运行期代码拷入交付目录 app/，并写 data/、uploads/ 占位。

    执行顺序刻意安排（design 决策 D8）：重叠防护必须先于 rmtree——
    --out 误指源码树内会触发"清空源码"的毁灭性事故，防护晚一步就晚了。
    """
    src_resolved = src_root.resolve()
    out_resolved = out_dir.resolve()
    # 双向包含都拒绝：out 在源码树内会删部分源码；源码树在 out 内会删全部源码。
    if out_resolved == src_resolved or out_resolved in src_resolved.parents or src_resolved in out_resolved.parents:
        raise ValueError(
            f"交付目录与源码目录重叠（{out_dir} 与 {src_root} ），"
            f"为防误删源码已拒绝执行，请换一个 --out 路径。"
        )

    # 幂等重建（spec 4.2-3）：重复打包不留旧文件残余。
    if out_dir.exists():
        shutil.rmtree(out_dir)

    app_dir = out_dir / "app"
    for item in PACKAGE_ITEMS:
        src = src_root / item.rel_path
        dst = app_dir / item.rel_path
        if item.kind == "dir":
            for path in iter_included_files(src):
                rel_parts = path.relative_to(src).parts
                target = dst.joinpath(*rel_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # data/ 与 uploads/ 是运行期落点（prescription.db / 上传图片）。
    # 用 .keep 占位而非纯目录条目：部分 Windows 解压工具会丢弃 zip 内
    # 空目录，.keep 是最稳方案（design 决策 D6）。
    for empty_dir_name in ("data", "uploads"):
        target_dir = out_dir / empty_dir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / ".keep").write_text("", encoding="ascii")


# ============================================================
# 四、样例图区：确定性选图 + 原文件名拷贝 + samples 说明渲染
# ============================================================


def select_sample_images(val_dir: Path) -> SamplePickResult:
    """五前缀各挑 1 张：命中列表 sorted 升序取首（design 决策 D4）。

    排序取首的"确定性"价值：文件系统返回顺序不可依赖，排序是全序；
    red_spider_mite 前缀下两种文件名形态（citrus_mite / spider_mite）
    无需特判即稳定选中字典序在前的形态。
    零写盘副作用——只列目录 + 排序，拷贝归 copy_samples 承担，
    这样本函数可被测试独立直测（用例 8）。
    """
    if not val_dir.is_dir():
        # val 目录整体缺失：五类全部落空，走软警告口径（spec 5.3.3-1）。
        return SamplePickResult(picked={}, missing=tuple(spec.prefix for spec in SAMPLE_IMAGE_SPECS))
    picked: dict[str, Path] = {}
    missing: list[str] = []
    for spec in SAMPLE_IMAGE_SPECS:
        hits = sorted(
            entry.name for entry in val_dir.iterdir() if entry.is_file() and entry.name.startswith(spec.prefix)
        )
        if hits:
            picked[spec.prefix] = val_dir / hits[0]
        else:
            missing.append(spec.prefix)
    return SamplePickResult(picked=picked, missing=tuple(missing))


def copy_samples(pick: SamplePickResult, samples_dir: Path) -> list[Path]:
    """按**原文件名**把挑选结果拷入 samples/（文件名保留红线，spec 5.3-4）。

    为什么禁止改名：离线演示客户端按图片文件名关键词路由预设诊断，
    改名会让样例图在离线模式全部落到兜底结论，演示穿帮。
    """
    samples_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for prefix in sorted(pick.picked):
        src = pick.picked[prefix]
        dst = samples_dir / src.name
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def render_samples_readme(pick: SamplePickResult) -> str:
    """生成 samples/README.md：逐张写明预期诊断结论与演示看点。

    某类未挑选到时如实标注"未挑选到"+ 自传图替代提示（spec 5.5.3-1）——
    演示脚本按文档走不能踩空。
    """
    lines = [
        "# samples · 演示样例图说明",
        "",
        "每张图上传到 Web Demo 后的预期结论如下。",
        "注意：离线演示模式按文件名关键词路由预设结论，**请勿重命名这些图片**。",
        "",
    ]
    for spec in SAMPLE_IMAGE_SPECS:
        src = pick.picked.get(spec.prefix)
        if src is None:
            lines.append(
                f"- 【未挑选到】{spec.label_cn}（label={spec.label}）："
                f"源目录未命中前缀 `{spec.prefix}`，演示时可自行上传同类照片替代。"
            )
        else:
            lines.append(f"- `{src.name}` → {spec.label_cn}（label={spec.label}）。{spec.highlights}")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# 五、启动器区：start.bat（GBK）/ start.ps1（utf-8-sig）/ requirements.txt（ASCII）
# ============================================================


def render_start_bat() -> str:
    """渲染 start.bat 内容：五步功能序列（spec 6.5）。

    模板字符集自我约束：只用 GBK 可编码字符（禁 emoji/生僻字），
    因为整文件将以 GBK 写入——Windows cmd 默认代码页 936 下
    UTF-8 中文必乱码（design 决策 D1）。
    独立窗口起服务是为了让"开浏览器"与"pause"步骤可达：
    同步阻塞执行的话 start.bat 永远走不到第 4 步。
    """
    return f"""@echo off
chcp 936 >nul
title 柚康 Web Demo 启动器
cd /d "%~dp0"
echo [柚康] 正在启动 Web Demo ...

rem ---------- 第一步：探测 Python 解释器 ----------
set "PYTHON_EXE="
if exist "D:\\anaconda3\\python.exe" (
    set "PYTHON_EXE=D:\\anaconda3\\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
    )
)
if "%PYTHON_EXE%"=="" (
    echo [柚康] 未找到 Python：请先安装 Python，或把 python.exe 加入 PATH 后重试。
    pause
    exit /b 1
)
echo [柚康] 使用解释器：%PYTHON_EXE%
echo [%date% %time%] 探测到解释器 %PYTHON_EXE% >> 运行日志.txt 2>nul

rem ---------- 第二步：安装依赖（失败不中断：离线模式不需要这些依赖也能跑） ----------
echo [柚康] 正在安装依赖（阿里云镜像）...
"%PYTHON_EXE%" -m pip install -r requirements.txt -i {PIP_MIRROR}
if errorlevel 1 (
    echo [柚康] 依赖安装失败：离线演示模式无需这些依赖，将继续启动。
)

rem ---------- 第三步：独立窗口启动服务（不阻塞后续步骤） ----------
echo [柚康] 正在启动本地服务（端口 {SERVER_PORT}）...
start "YouKang-WebDemo" cmd /c ""%PYTHON_EXE%" app\\web_demo\\server.py --port {SERVER_PORT}"

rem ---------- 等待服务就绪：消除浏览器先开被拒的秒级窗口 ----------
timeout /t 3 /nobreak >nul

rem ---------- 第四步：打开浏览器 ----------
start http://127.0.0.1:{SERVER_PORT}

rem ---------- 第五步：保留窗口（出错不闪退） ----------
echo [%date% %time%] 启动流程执行完毕 >> 运行日志.txt 2>nul
echo [柚康] 启动完成。若浏览器未自动打开，请手动访问 http://127.0.0.1:{SERVER_PORT}
pause
"""


def render_start_ps1() -> str:
    """渲染 start.ps1：与 start.bat 五步一一对应的 PowerShell 版。

    处理含中文的路径更稳（PowerShell 原生 Unicode）；
    用 $PSScriptRoot 显式定位脚本目录，从任意工作目录调用都成立。
    """
    return f"""# 柚康 Web Demo 启动器（PowerShell 版，处理中文路径更稳）
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

# ---------- 第一步：探测 Python 解释器 ----------
$pythonExe = $null
if (Test-Path "D:\\anaconda3\\python.exe") {{
    $pythonExe = "D:\\anaconda3\\python.exe"
}} else {{
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) {{ $pythonExe = "python" }}
}}
if (-not $pythonExe) {{
    Write-Host "[柚康] 未找到 Python：请先安装 Python，或把 python.exe 加入 PATH 后重试。"
    Read-Host "按回车键退出"
    exit 1
}}
Write-Host "[柚康] 使用解释器：$pythonExe"

# ---------- 第二步：安装依赖（失败不中断：离线模式不需要这些依赖也能跑） ----------
Write-Host "[柚康] 正在安装依赖（阿里云镜像）..."
& $pythonExe -m pip install -r requirements.txt -i {PIP_MIRROR}

# ---------- 第三步：独立窗口启动服务（不阻塞后续步骤） ----------
Write-Host "[柚康] 正在启动本地服务（端口 {SERVER_PORT}）..."
Start-Process -FilePath $pythonExe -ArgumentList "app\\web_demo\\server.py", "--port", "{SERVER_PORT}" -WorkingDirectory $PSScriptRoot

# ---------- 等待服务就绪：消除浏览器先开被拒的秒级窗口 ----------
Start-Sleep -Seconds 3

# ---------- 第四步：打开浏览器 ----------
Start-Process "http://127.0.0.1:{SERVER_PORT}"

# ---------- 第五步：保留窗口（出错不闪退） ----------
Write-Host "[柚康] 启动完成。若浏览器未自动打开，请手动访问 http://127.0.0.1:{SERVER_PORT}"
Read-Host "按回车键退出"
"""


def write_launchers(out_dir: Path) -> None:
    """三编码分治写盘（design 决策 D1）。

    start.bat 用 GBK（cmd 代码页 936）；start.ps1 用 utf-8-sig 带 BOM
    （PowerShell 5.1 无 BOM 的 UTF-8 会按 ANSI 误读）；requirements.txt
    用 ASCII（内容本就是纯 ASCII 包名）。
    """
    (out_dir / "start.bat").write_text(render_start_bat(), encoding="gbk")
    (out_dir / "start.ps1").write_text(render_start_ps1(), encoding="utf-8-sig")
    (out_dir / "requirements.txt").write_text("\n".join(REQUIREMENTS_LINES) + "\n", encoding="ascii")


# ============================================================
# 六、文档区：README.md / DEMO_SCRIPT.md（队友视角）
# ============================================================


def render_readme() -> str:
    """渲染 README.md：三步跑起来 / 两种模式 / 目录说明 / FAQ 五条 / 免责。

    面向"可能不懂 Python 的队友"，只写操作不写实现；
    setx 不影响当前进程——"重开窗口"是队友最常踩的坑，必须写明。
    """
    return f"""# 柚康 · 柚子病虫害智能诊断 Web Demo

上传柚子叶片照片，即可得到病害诊断与用药处方建议。

## 三步跑起来

1. 解压（或拷贝）整个文件夹到本机任意目录；
2. 双击 `start.bat`（第一次运行会自动安装依赖，需要几分钟）；
3. 浏览器自动打开演示页面（若没自动打开，手动访问 http://127.0.0.1:{SERVER_PORT}）。

## 两种运行模式

| 模式 | 触发条件 | 说明 |
|---|---|---|
| 在线模式 | 已配置 `MAAS_API_KEY` | 走真实大模型诊断，会消耗 Token |
| 离线演示模式 | 未配置 Key（默认） | 界面完全一致，结论为预置值，Token 为模拟值 |

配置真实诊断的步骤（可选）：

1. 打开命令行窗口，执行 `setx MAAS_API_KEY "你的Key"`；
2. **关闭并重开命令行窗口**（setx 不影响当前已打开的窗口，重开才生效）；
3. 重新双击 `start.bat`，页面顶部徽章变为"在线模式"。

## 目录说明

| 目录/文件 | 一句话说明 |
|---|---|
| `app/` | 运行代码（Web 服务 + 诊断链路 + 处方规则引擎） |
| `samples/` | 演示用样例图（含每张图的预期结论说明） |
| `data/` | 运行时自动生成的数据库文件 |
| `uploads/` | 运行时上传图片的存放目录 |
| `start.bat` / `start.ps1` | 启动脚本（双击前者即可，后者为备选） |
| `requirements.txt` | 依赖清单（首次启动自动安装） |
| `DEMO_SCRIPT.md` | 汇报演示脚本（60 秒版 / 3 分钟版） |

## 常见问题（FAQ）

1. **端口被占用怎么办？** 用记事本打开 `start.bat`，把里面的 `7860` 改成其他端口（如 `7861`），保存后重新双击；浏览器地址同步改端口。
2. **pip 装不上怎么办？** 依赖安装失败不影响离线演示——启动脚本会继续起服务。也可以换一个网络环境后重新双击 `start.bat`。
3. **浏览器没自动打开？** 手动访问 http://127.0.0.1:{SERVER_PORT} 即可。
4. **图片上传失败？** 支持 jpg / jpeg / png / webp / bmp 格式，单张不超过 10MB，单次最多 6 张；超限会收到中文提示。
5. **为什么显示"离线演示模式"？** 因为没有配置 `MAAS_API_KEY`。离线模式界面与在线完全一致，仅诊断结论为预置值，适合无网络的演示场合。

## 免责声明

农业建议仅供参考，实际用药请遵当地植保站意见。
"""


def render_demo_script() -> str:
    """渲染 DEMO_SCRIPT.md：60 秒 + 3 分钟两版演示脚本。

    每一步都标注 Token 消耗——这是导师明确关注的指标；
    口径必须写清：在线为真实消耗、离线为模拟值（界面 Token 徽章同口径）。
    """
    return f"""# 柚康 Web Demo · 汇报演示脚本

> Token 标注口径：**在线模式为真实消耗量级，离线演示模式为模拟值**
> （模拟值同样走完整链路统计，用于证明"每次问答都烧 Token"的机制成立）。
> 界面右上角 Token 徽章实时累计输入/输出/合计，可随时指给评委看。

## 60 秒版（快速过链路）

| 步骤 | 操作 | 讲解要点 | Token 消耗 |
|---|---|---|---|
| 1 | 上传叶片图（samples/ 里的样例图即可） | "柚农只需要拍照上传" | 约 1.5k～2k（视觉诊断一次调用） |
| 2 | 等待出诊断 | "模型返回病害名 + 置信度 + 症状描述 + 与易混病害的区分点" | 已含在上一步 |
| 3 | 展开右侧"诊断详情"里的处方卡片 | "可用药 / 禁用药两栏，禁用项带中文理由——规则引擎把安全规则锁死了" | 约 1k～1.5k（处方文案一次调用） |
| 4 | 指页面顶部 Token 徽章 | "每次问答的 Token 消耗实时可见、会话内累计" | 累计值即当前展示 |
| 5 | 打开知识库面板（左侧栏底部入口） | "诊断依据来自本地知识库：当月风险病害 + 防治建议 + 数据来源标注" | 0（本地查询，不烧 Token） |

## 3 分钟版（在 60 秒版基础上加四幕）

### 第一幕：换个地块，看规则引擎拒绝某药
- 操作：新建对话，填不同地块名（如"示范果园A"），再上传同一张病叶图。
- 讲解："同一张图，换到近期用过同组药的地块，处方里这种药就被拒了——
  拒绝理由是中文的：抗药性轮换 / 安全间隔期，柚农看得懂。"
- Token：约 2k～3k（诊断 + 处方各一次调用）。

### 第二幕：黄龙病触发检疫上报
- 操作：上传 samples/ 里的 greening 样例图。
- 讲解："黄龙病是检疫性病害，系统不推荐任何治疗药剂，只提示：
  上报当地植保部门、挖除病株、防治柑橘木虱、选用无病苗木——
  这是农业合规红线，由本地护栏锁死，不依赖大模型自觉。"
- Token：约 1.5k～2k（诊断一次；处方为空但护栏校验照走）。

### 第三幕：多轮追问（鉴别问诊）
- 操作：诊断结果带追问问题时，点选答案继续（如"能否补拍叶背照片"的选项）。
- 讲解："置信度不够时，智能体主动追问而不是硬猜——补一张图后置信度从
  0.5x 提到 0.8x，这就是 Agent 的价值。"
- Token：每轮追问约 1k～2k（问答累计，徽章数字实时上涨）。

### 第四幕：离线模式对比
- 操作：说明当前机器未配置 Key（或另开一台无 Key 机器跑同一 zip 包）。
- 讲解："没有 API Key、没有数据库、断网，界面照样全功能可演示——
  离线模式结论为预置值、Token 为模拟值，交付包开箱即跑。"
- Token：模拟值（机制口径与在线一致）。

> 若 samples/ 缺某类样例图（见 samples/README.md 的"未挑选到"标注），
> 对应步骤可临时自传同类照片替代。
"""


def write_documents(out_dir: Path, pick: SamplePickResult) -> None:
    """写 README.md / DEMO_SCRIPT.md / samples/README.md（均 UTF-8）。

    动态内容只来自样例图挑选结果——静态模板内置在脚本里，
    不依赖外部模板文件（spec 1.2-5）。
    """
    (out_dir / "README.md").write_text(render_readme(), encoding="utf-8")
    (out_dir / "DEMO_SCRIPT.md").write_text(render_demo_script(), encoding="utf-8")
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    (samples_dir / "README.md").write_text(render_samples_readme(pick), encoding="utf-8")


# ============================================================
# 七、zip 区：打包 + 排除复用 + 自校验 + 产物报告
# ============================================================


def create_zip(out_dir: Path, zip_path: Path) -> ZipReport:
    """把交付目录打成 zip：以目录名为 zip 内容根，写后重开自校验。

    遍历时复用 is_excluded 做**防御性再过滤**——交付目录本身已经
    过滤过一遍，这里成本为零，却防住未来清单演进引入的遗漏（design 决策 D5）。
    自校验（testzip 校验 CRC）通过后才生成报告：报告打印前先证明 zip 完整。
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    root_name = out_dir.name
    file_names: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_included_files(out_dir):
            rel = PurePosixPath(path.relative_to(out_dir).as_posix())
            arcname = f"{root_name}/{rel}"
            zf.write(path, arcname)
            file_names.append(arcname)

    # 写后重开自校验：可读、无损坏（spec 5.6.1-5）。
    with zipfile.ZipFile(zip_path) as zf:
        bad_file = zf.testzip()
        if bad_file is not None:
            raise OSError(f"zip 自校验失败（CRC 损坏）：{bad_file}")
        file_count = len(zf.namelist())

    size_bytes = zip_path.stat().st_size
    if size_bytes > ZIP_SIZE_WARN_BYTES:
        # 白名单拷贝机制下超限本不可达（数据集/权重进不了包），
        # 只警告不拦截：硬拦截反而引入无意义的失败面（design 决策 D12）。
        print(f"[打包] 警告：zip 体积 {size_bytes / 1048576:.1f}MB 超过 50MB 红线，请检查是否误打大文件。")
    return ZipReport(
        zip_path=zip_path,
        file_count=file_count,
        first_files=tuple(file_names[:20]),
        size_bytes=size_bytes,
    )


# ============================================================
# 八、gitignore 区：幂等追加交付产物段
# ============================================================


def update_gitignore(project_root: Path) -> bool:
    """向项目根 .gitignore 幂等追加交付产物忽略条目，返回是否发生追加。

    只追加不删改既有条目（spec 5.7-3）——借更新之机删改既有规则是红线。
    读写失败走软警告口径：git 卫生问题不阻断交付包生成（spec 5.7.3-1）。
    """
    gitignore_path = project_root / ".gitignore"
    try:
        current = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    except OSError as exc:
        print(f"[打包] 警告：.gitignore 读取失败（{exc}），请手工补交付产物忽略条目。")
        return False

    existing_lines = {line.strip() for line in current.splitlines()}
    pending = [line for line in GITIGNORE_APPEND_LINES if line not in existing_lines]
    section_needed = GITIGNORE_SECTION_TITLE not in existing_lines
    if not pending and not section_needed:
        return False

    addition_lines: list[str] = []
    if section_needed:
        # 空行分隔 + 分段标题，沿用既有 # ---------- 段名 ---------- 风格。
        if current and not current.endswith("\n"):
            addition_lines.append("")
        addition_lines.append(GITIGNORE_SECTION_TITLE)
    addition_lines.extend(pending)
    try:
        with gitignore_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(addition_lines) + "\n")
    except OSError as exc:
        print(f"[打包] 警告：.gitignore 写入失败（{exc}），请手工补交付产物忽略条目。")
        return False
    print(f"[打包] .gitignore 已追加 {len(pending)} 条交付产物忽略条目。")
    return True


# ============================================================
# 九、编排区：build_package 主函数与 CLI main 分离
# ============================================================


def build_package(
    src_root: Path,
    out_dir: Path,
    val_dir: Path,
    project_root: Path,
    zip_path: Path | None,
) -> int:
    """完整打包编排（①校验 → ②拷贝 → ③选图 → ④启动器 → ⑤文档 → ⑥zip → ⑦gitignore）。

    路径全部由调用方注入（design 决策 D7）——CLI 解析与打包主函数分离，
    测试才能注入 tmp_path 而不污染仓库、残缺源树用例才能自造输入。
    返回退出码：0 成功；2 由调用方捕获 MissingPrerequisiteError/ValueError 转换；
    3 写盘类错误（如实告知交付目录已成功的事实）。
    """
    missing = validate_prerequisites(src_root)
    if missing:
        # 硬校验先于一切写盘动作：报错退出时不产生半成品 out 目录（spec 5.1.1-4）。
        raise MissingPrerequisiteError(format_missing(missing))
    print(f"[打包] 前置校验通过：{len(PACKAGE_ITEMS)} 项清单文件齐备。")

    try:
        copy_package_files(src_root, out_dir)
        print(f"[打包] 运行期代码已拷贝至 {out_dir / 'app'}。")

        pick = select_sample_images(val_dir)
        for prefix in pick.missing:
            # 软警告：样例图是演示增强件，缺失不影响 Demo 核心可用性（spec 5.3.1-5）。
            print(f"[打包] 警告：样例图前缀 {prefix} 未挑选到（源目录：{val_dir}），不影响打包。")
        copy_samples(pick, out_dir / "samples")
        print(f"[打包] 样例图已挑选 {len(pick.picked)} 张（缺失 {len(pick.missing)} 类）。")

        write_launchers(out_dir)
        print("[打包] 启动器已生成：start.bat（GBK）/ start.ps1 / requirements.txt。")

        write_documents(out_dir, pick)
        print("[打包] 文档已生成：README.md / DEMO_SCRIPT.md / samples/README.md。")

        if zip_path is not None:
            report = create_zip(out_dir, zip_path)
            print(f"[打包] zip 已生成：{report.zip_path}")
            print(f"[打包] zip 内文件总数：{report.file_count}")
            print(f"[打包] zip 体积：{report.size_bytes / 1048576:.1f}MB")
            print("[打包] zip 内前 20 个文件名：")
            for name in report.first_files:
                print(f"         - {name}")
    except OSError as exc:
        print(f"[打包] 报错：写盘失败（{exc}）。")
        if out_dir.exists():
            print(f"[打包] 说明：交付目录 {out_dir} 的生成状态以磁盘实际内容为准，zip 可稍后重试。")
        return 3

    update_gitignore(project_root)
    print(f"[打包] 完成：交付目录 {out_dir}")
    return 0


def main() -> int:
    """CLI 入口：argparse 解析 + 路径推导（全部从脚本 __file__ 出发，禁止硬编码盘符）。"""
    parser = argparse.ArgumentParser(
        description="Web Demo 交付打包：把 Web Demo 打成队友拿到就能跑的交付包（免安装/免配置/免密钥）"
    )
    parser.add_argument("--out", required=True, help="交付目录路径（如 E:\\柚子病虫害AI识别\\web-demo）")
    parser.add_argument("--zip", action="store_true", help="打包完成后在项目根生成 YouKang-WebDemo-v0.1.zip")
    args = parser.parse_args()

    # 路径推导链：脚本在 code/pomelo-algorithm/tools/ 下，
    # 上两级是源码根，再上两级是项目根（数据集与 .gitignore 的落点）。
    src_root = Path(__file__).resolve().parent.parent
    project_root = src_root.parent.parent
    val_dir = project_root / "dataset" / "pomelo_yolo" / "images" / "val"
    out_dir = Path(args.out)
    zip_path = project_root / ZIP_FILENAME if args.zip else None

    print(f"[打包] 源码根：{src_root}")
    print(f"[打包] 交付目录：{out_dir}")
    if zip_path is not None:
        print(f"[打包] zip 产物：{zip_path}")

    try:
        return build_package(src_root, out_dir, val_dir, project_root, zip_path)
    except MissingPrerequisiteError as exc:
        print(f"[打包] 报错：前置产物缺失，打包终止（未产生任何交付文件）。\n{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[打包] 报错：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())