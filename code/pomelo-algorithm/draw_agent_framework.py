"""绘制「柚康」植保智能体框架结构图。

样式与导出复用 scipilot-figure-skill 的 setup_style / export_figure。
运行：
    python code/pomelo-algorithm/draw_agent_framework.py
输出：figures/agent_framework.{png,pdf,svg}
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

SKILL = Path(r"C:/Users/Legion/.workbuddy/skills/scipilot-figure-skill")
sys.path.insert(0, str(SKILL / "scripts"))

from setup_style import setup_style  # noqa: E402
from export_figure import export_figure  # noqa: E402

# ---------- 出版级样式（中文 + 通用期刊预设） ----------
setup_style(journal="general", lang="zh")
# Windows 下优先用微软雅黑（有真正的 bold 字重，Noto Sans SC 没有）
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "Noto Sans SC", "SimHei"]

# Okabe-Ito 色盲安全配色
C_BLUE = "#0072B2"
C_ORANGE = "#E69F00"
C_GREEN = "#009E73"
C_PURPLE = "#CC79A7"
C_RED = "#D55E00"
C_TEXT = "#1A1A1A"


def box(ax, x, y, w, h, text, fc, ec=C_TEXT, fs=9.5, bold=False):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.3,rounding_size=1.1",
        linewidth=1.1, edgecolor=ec, facecolor=fc, zorder=2,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=C_TEXT, zorder=3,
            fontweight="bold" if bold else "normal", linespacing=1.35)


def band(ax, y, h, text):
    patch = FancyBboxPatch(
        (0.5, y), 4.6, h,
        boxstyle="round,pad=0.15,rounding_size=0.7",
        linewidth=0.8, edgecolor=C_TEXT, facecolor="#D9D9D9", zorder=2,
    )
    ax.add_patch(patch)
    ax.text(2.8, y + h / 2, text, ha="center", va="center", fontsize=9,
            color=C_TEXT, zorder=3, fontweight="bold", rotation=90)


def arrow(ax, x1, y1, x2, y2, color=C_TEXT, ls="-", rad=0.0):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=11,
        linewidth=1.3, color=color, linestyle=ls, zorder=4,
        connectionstyle=f"arc3,rad={rad}",
    ))


def main() -> None:
    fig, ax = plt.subplots(figsize=(12.4, 8.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    ax.text(1, 98.2, "柚康 · 柚子病虫害植保智能体框架", fontsize=14,
            fontweight="bold", ha="left", va="center")
    ax.text(82, 98.2, "时序闭环", fontsize=12, fontweight="bold",
            ha="center", va="center", color=C_GREEN)

    # ============ L0 输入守门 ============
    band(ax, 86, 10, "输入")
    box(ax, 6, 87, 16, 8, "拍照 / 选图\n（HarmonyOS）", "#DEEBF7", C_BLUE)
    box(ax, 24, 87, 22, 8, "图像质量门\n清晰度 / 曝光 / 叶片占比", "#DEEBF7", C_BLUE, bold=True)
    box(ax, 48, 87, 19, 8, "不合格 → 即时\n提示重拍", "#FFF2CC", C_ORANGE)
    arrow(ax, 22, 91, 24, 91)
    arrow(ax, 46, 91, 48, 91)

    # ============ L1 感知（端云双路） ============
    band(ax, 72, 12, "感知")
    box(ax, 6, 73, 30, 10, "端侧：MindSpore Lite\nYOLOv5s（.ms）离线推理\n无网可用 · 低延迟",
        "#DEEBF7", C_BLUE, bold=True)
    box(ax, 38, 73, 29, 10, "云端：ModelArts 在线服务\nYOLOv5s 检测框 + top-2 类别\n复杂样本复核",
        "#FCE4D6", C_ORANGE, bold=True)
    arrow(ax, 26, 87, 21, 83.5)
    arrow(ax, 44, 87, 52.5, 83.5)

    # ============ L2 路由与融合 ============
    band(ax, 61, 9, "路由")
    box(ax, 6, 62, 61, 7, "端云路由：无网 → 端侧 ｜ 低置信或 top-2 接近 → 云端复核\n结果融合，UI 标注识别来源",
        "#EAEAEA", C_TEXT, fs=9.2)
    arrow(ax, 21, 73, 21, 69.5)
    arrow(ax, 52.5, 73, 52.5, 69.5)

    # ============ L3 Agent 决策 ============
    band(ax, 38, 21, "决策")
    box(ax, 6, 42, 17, 13, "诊断状态判定\n置信度 +\ntop-2 差额", "#DFF2E9", C_GREEN, bold=True)
    box(ax, 26, 53, 41, 5.6, "① 确诊：高置信单类 → 直接生成处方", "#FFFFFF", C_GREEN, fs=9)
    box(ax, 26, 46, 41, 5.6, "② 不确定（top-2 接近）→ 鉴别式问诊：病斑隆起？叶背同斑？",
        "#FFF2CC", C_ORANGE, fs=9, bold=True)
    box(ax, 26, 39, 41, 5.6, "③ 无检测框 → 判为健康（负样本机制）", "#FFFFFF", C_GREEN, fs=9)
    arrow(ax, 23, 53, 26, 55.8)
    arrow(ax, 23, 49.5, 26, 48.8)
    arrow(ax, 23, 45.5, 26, 41.8)
    arrow(ax, 36.5, 39, 36.5, 37.6, C_PURPLE)

    # ============ L4 处方引擎 ============
    band(ax, 25, 11, "处方")
    box(ax, 6, 26, 17, 10, "植保处方引擎\n（规则硬约束）", "#F7E6F0", C_PURPLE, bold=True)
    box(ax, 25, 26, 13, 10, "安全间隔期\nPHI ≤ 距采收天数", "#FFFFFF", C_PURPLE, fs=8.6)
    box(ax, 40, 26, 13, 10, "抗药性轮换\nFRAC/IRAC 分组", "#FFFFFF", C_PURPLE, fs=8.6)
    box(ax, 55, 26, 12, 10, "复配禁忌\n过滤", "#FFFFFF", C_PURPLE, fs=8.6)

    # ============ L5 护栏与输出 ============
    band(ax, 13, 10, "输出")
    box(ax, 6, 14, 17, 8.5, "合规护栏\n数值带来源 · 禁编造\n检疫性病害上报", "#FBE5DC", C_RED,
        fs=8.4, bold=True)
    box(ax, 25, 14, 64, 8.5, "处方卡片：病名 + 置信度 + 病斑框 ｜ 药剂与剂量 ｜ 安全间隔期 ｜ 轮换建议\n（端侧展示或由智能体多轮问答给出）",
        "#DFF2E9", C_GREEN, fs=9, bold=True)
    arrow(ax, 14.5, 26, 14.5, 23, C_PURPLE)
    arrow(ax, 23, 18.2, 25, 18.2, C_RED)
    arrow(ax, 57, 26, 57, 23, C_PURPLE)

    # ============ L6 知识与数据层 ============
    band(ax, 3, 8, "数据")
    box(ax, 6, 4, 83, 7, "知识与数据层（RDS）：病害档案 ｜ 农药规则库（PHI / FRAC-IRAC / 禁忌）｜ 识别历史 ｜ 每条数据带来源字段",
        "#EAEAEA", C_TEXT, fs=9.2)
    ax.add_patch(FancyArrowPatch((57, 14), (57, 11.4), arrowstyle="<|-|>",
                                 mutation_scale=10, linewidth=1.2, color=C_TEXT, zorder=4))

    # ============ 右侧：时序闭环 ============
    box(ax, 70, 80, 25, 8.5, "① 拍照归档\n（时间 / 病斑面积）", "#DFF2E9", C_GREEN, fs=8.8)
    box(ax, 70, 68.5, 25, 8.5, "② 7 天后复拍同叶", "#DFF2E9", C_GREEN, fs=8.8)
    box(ax, 70, 57, 25, 8.5, "③ 病斑面积变化率", "#DFF2E9", C_GREEN, fs=8.8)
    box(ax, 70, 42, 25, 10, "④ 扩散 → 换药 / 升级\n好转 → 维持方案", "#FFF2CC", C_ORANGE, fs=8.8)
    arrow(ax, 82.5, 80, 82.5, 77.5, C_GREEN)
    arrow(ax, 82.5, 68.5, 82.5, 66, C_GREEN)
    arrow(ax, 82.5, 57, 82.5, 52.5, C_GREEN)

    # ④ → 处方引擎（扩散则重新处方）
    arrow(ax, 70, 46, 67.5, 33, C_RED, ls="--", rad=-0.25)
    ax.text(66.6, 37.8, "扩散 → 重新处方", fontsize=7.6, color=C_RED, ha="right")

    # 处方卡片 → 归档（每次识别入档，沿最右侧走线）
    ax.plot([89.5, 97.2], [22.5, 22.5], color=C_GREEN, lw=1.3, ls="--", zorder=1)
    ax.plot([97.2, 97.2], [22.5, 84.2], color=C_GREEN, lw=1.3, ls="--", zorder=1)
    arrow(ax, 97.2, 84.2, 95.2, 84.2, C_GREEN, ls="--")
    ax.text(98.0, 50, "每次识别结果归档", fontsize=7.6, color=C_GREEN,
            rotation=90, va="center", ha="center")

    out = Path("E:/柚子病虫害AI识别/figures/agent_framework")
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = export_figure(fig, basename=str(out), formats=["png", "pdf", "svg"],
                          size_inches=(12.4, 8.6), dpi=300, grayscale_preview=False)
    print("已导出:")
    for p in paths:
        print("  ", p)


if __name__ == "__main__":
    main()
