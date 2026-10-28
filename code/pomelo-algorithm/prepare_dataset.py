"""数据集准备与切分脚本（spec 5.1，design 接口 1）。

将分类数据集（--src，一级子目录名为类别名英文）整理为 YOLOv5 标准数据集（--dst）：
类别映射（4 类体系，未知类别丢弃）、8:1:1 随机切分（种子 42）、整图伪框标签、
YOLOv5 目录结构、citrus.yaml 配置、每类每 split 统计报告（打印 + dataset_stats.txt）。
仅依赖 Python 标准库（os/shutil/random/pathlib，spec 5.1.1-8）。

用法：
    python prepare_dataset.py --src "E:/datasets/raw" --dst "E:/datasets/pomelo_yolo"
"""
import argparse
import random
import shutil
import sys
from pathlib import Path

from labelmap import CLASS_NAMES, is_negative_class, normalize_class_name

SEED: int = 42
SPLITS: tuple = ("train", "val", "test")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# 负样本（健康叶 + 易误判非目标类）：不占检测类别编号，生成空标注文件
NEGATIVE_ID: int = -1
NEGATIVE_BUCKET: str = "__negative__"   # 统计报告中的桶名
NEGATIVE_PREFIX: str = "neg"            # 输出文件名前缀


def scan_class_dirs(src: Path) -> dict:
    """扫描 src 一级类别子目录，经 labelmap 归一化映射。

    检测类 → 类别编号；负样本类 → NEGATIVE_ID（生成空标注）；
    其余未知类别丢弃（spec 5.1.1-1/2）。
    """
    class_images: dict = {}
    for entry in sorted(src.iterdir()):
        if not entry.is_dir():
            continue
        class_id = normalize_class_name(entry.name)
        if class_id is None:
            if is_negative_class(entry.name):
                class_id = NEGATIVE_ID
            else:
                print(f"[数据准备] 丢弃未知类别目录: {entry.name}")
                continue
        imgs = [p for p in sorted(entry.rglob("*"))
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        class_images.setdefault(class_id, []).extend(imgs)
    return class_images


def split_images(images: list, rng: random.Random) -> dict:
    """类别内随机打乱后按 8:1:1 切分（种子 42，可复现，spec 5.1.1-3）。"""
    shuffled = list(images)
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_test = int(n * 0.1)
    n_val = int(n * 0.1)
    return {
        "train": shuffled[n_test + n_val:],
        "val": shuffled[n_test:n_test + n_val],
        "test": shuffled[:n_test],
    }


def _unique_stem(dst_dir: Path, stem: str, suffix: str) -> str:
    """目标同名冲突时追加序号，保证图片与标签使用同一 stem。"""
    if not (dst_dir / f"{stem}{suffix}").exists():
        return stem
    i = 1
    while True:
        cand = f"{stem}_{i}"
        if not (dst_dir / f"{cand}{suffix}").exists():
            return cand
        i += 1


def place_dataset(class_splits: dict, dst: Path) -> None:
    """生成 YOLOv5 目录结构并复制图片、生成整图伪框标签（spec 5.1.1-4/5）。"""
    for split in SPLITS:
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)
    for class_id, splits in class_splits.items():
        for split, items in splits.items():
            img_dir = dst / "images" / split
            lbl_dir = dst / "labels" / split
            bucket = NEGATIVE_PREFIX if class_id == NEGATIVE_ID else CLASS_NAMES[class_id]
            for img in items:
                stem = _unique_stem(img_dir, f"{bucket}_{img.stem}", img.suffix.lower())
                shutil.copy2(img, img_dir / f"{stem}{img.suffix.lower()}")
                # 负样本写入空文件：训练时作为"无目标"样本，抑制误报
                text = "" if class_id == NEGATIVE_ID else f"{class_id} 0.5 0.5 1.0 1.0\n"
                (lbl_dir / f"{stem}.txt").write_text(text, encoding="utf-8")


def write_citrus_yaml(dst: Path) -> None:
    """生成 citrus.yaml：路径占位符 + nc:4 + names（spec 5.1.1-5）。"""
    content = (
        "# YOLOv5 dataset config (pomelo-algorithm)\n"
        "# 注意：以下 train/val/test 为路径占位符，训练/评估前必须修正为实际环境绝对路径\n"
        "#（ModelArts Notebook 环境: /home/ma-user/work/dataset）\n"
        "train: <DATASET_ROOT>/images/train\n"
        "val: <DATASET_ROOT>/images/val\n"
        "test: <DATASET_ROOT>/images/test\n"
        "\n"
        "nc: 4\n"
        "names: [" + ", ".join(CLASS_NAMES) + "]\n"
    )
    (dst / "citrus.yaml").write_text(content, encoding="utf-8")


def build_stats(class_splits: dict) -> dict:
    return {(NEGATIVE_BUCKET if cid == NEGATIVE_ID else CLASS_NAMES[cid]):
            {s: len(items) for s, items in splits.items()}
            for cid, splits in class_splits.items()}


def render_stats(stats: dict, title: str = "统计报告（8:1:1 切分, seed=42）",
                 rf_stats: dict | None = None, skipped_splits: list | None = None) -> str:
    """渲染统计报告文本；某类别某 split 为 0 时明确标记（spec 5.1.1-6）。"""
    all_names = list(CLASS_NAMES) + [NEGATIVE_BUCKET]
    lines = [title, f"{'class':<20}{'train':>8}{'val':>8}{'test':>8}"]
    for name in all_names:
        row = f"{name:<20}"
        for s in SPLITS:
            row += f"{stats.get(name, {}).get(s, 0):>8}"
        lines.append(row)
    lines.append(f"{'total':<20}" + "".join(
        f"{sum(stats.get(n, {}).get(s, 0) for n in all_names):>8}" for s in SPLITS))
    # 负样本为 0 属正常情况（不是必须），不参与 0 样本告警
    zero_marks = [f"{n}/{s}" for n in CLASS_NAMES for s in SPLITS
                  if stats.get(n, {}).get(s, 0) == 0]
    if zero_marks:
        lines.append("[0 样本] 以下类别/split 无样本（数据集已生成，训练环节须拒绝启动）: "
                     + ", ".join(zero_marks))
    if rf_stats is not None:
        lines.append("rf_ 来源计数（Roboflow 合并新增，spec 5.1.1-7.7）:")
        lines.append(f"{'class':<20}{'train':>8}{'val':>8}{'test':>8}")
        for name in all_names:
            row = f"{name:<20}"
            for s in SPLITS:
                row += f"{rf_stats.get(name, {}).get(s, 0):>8}"
            lines.append(row)
        lines.append(f"{'rf_total':<20}" + "".join(
            f"{sum(rf_stats.get(n, {}).get(s, 0) for n in all_names):>8}" for s in SPLITS))
    if skipped_splits:
        lines.append("[跳过] Roboflow 缺失 split 子目录: " + ", ".join(skipped_splits))
    return "\n".join(lines)


def emit_stats(text: str, dst: Path | None = None) -> None:
    """统计报告：打印至命令行并存为 dataset_stats.txt（spec 5.1.1-6）。"""
    print(text)
    if dst is not None:
        (dst / "dataset_stats.txt").write_text(text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="数据集准备与切分（YOLOv5 整图伪框）")
    parser.add_argument("--src", required=True, help="原始数据集根目录（一级子目录名为类别名英文）")
    parser.add_argument("--dst", required=True, help="YOLOv5 数据集输出目录")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)

    if not src.is_dir():
        print(f"[数据准备] 报错：--src 路径无效（目录不存在）: {src}")
        return 2

    class_images = scan_class_dirs(src)
    if not class_images:
        print("[数据准备] 报错：--src 下无可识别类别子目录，请检查目录名"
              "（映射规则见 labelmap.py）")
        return 2

    rng = random.Random(SEED)
    class_splits = {cid: split_images(imgs, rng) for cid, imgs in class_images.items()}

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    place_dataset(class_splits, dst)
    write_citrus_yaml(dst)
    emit_stats(render_stats(build_stats(class_splits)), dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())