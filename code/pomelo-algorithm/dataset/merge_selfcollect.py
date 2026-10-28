"""自采数据并入脚本（merge_selfcollect）。

把自采目录（按类别分子目录，已用 LabelImg 标注为 YOLO 格式）
合并进 dataset/pomelo_yolo，并重新输出统计报告。

同时保证不破坏原有 8:1:1 的 val/test 划分（自采图按同类比例切分）。

用法：
    python merge_selfcollect.py --src /path/to/selfcollect --dst /path/to/dataset/pomelo_yolo
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path


# 类别编号（与 labelmap.py 一致）
CLASS_NAMES = ("red_spider_mite", "anthracnose", "canker", "healthy")
CLASS_TO_ID = {name: idx for idx, name in enumerate(CLASS_NAMES)}

# 切分比例
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
TEST_RATIO = 0.1

# 随机种子
SEED = 42


def _split_indices(total: int, seed: int = SEED) -> dict[str, list[int]]:
    """将 0..total-1 的索引按 8:1:1 切分。"""
    rng = random.Random(seed)
    indices = list(range(total))
    rng.shuffle(indices)

    train_end = int(total * TRAIN_RATIO)
    val_end = train_end + int(total * VAL_RATIO)

    return {
        "train": indices[:train_end],
        "val": indices[train_end:val_end],
        "test": indices[val_end:],
    }


def _read_label_file(txt_path: Path) -> list[str]:
    """读取标注文件。"""
    if not txt_path.exists():
        return []
    return txt_path.read_text(encoding="utf-8").strip().splitlines()


def _write_label_file(txt_path: Path, lines: list[str]) -> None:
    """写入标注文件。"""
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _get_image_files(class_dir: Path) -> list[Path]:
    """获取目录下所有图片文件。"""
    extensions = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG", ".bmp", ".BMP"}
    return sorted(
        [f for f in class_dir.iterdir() if f.suffix in extensions]
    )


def _get_label_file(image_path: Path) -> Path:
    """获取对应的标注文件路径。"""
    return image_path.with_suffix(".txt")


def _is_healthy(image_path: Path) -> bool:
    """判断是否为健康叶（空标注文件）。"""
    label_path = _get_label_file(image_path)
    if not label_path.exists():
        return True
    return label_path.stat().st_size == 0


def _copy_image_and_label(
    image_path: Path,
    dst_dir: Path,
    split: str,
    new_name: str | None = None,
) -> None:
    """复制图片和标注文件到目标目录。"""
    dst_image_dir = dst_dir / "images" / split
    dst_label_dir = dst_dir / "labels" / split
    dst_image_dir.mkdir(parents=True, exist_ok=True)
    dst_label_dir.mkdir(parents=True, exist_ok=True)

    name = new_name or image_path.stem
    ext = image_path.suffix

    # 复制图片
    dst_image_path = dst_image_dir / (name + ext)
    shutil.copy2(image_path, dst_image_path)

    # 复制标注文件
    label_path = _get_label_file(image_path)
    if label_path.exists():
        dst_label_path = dst_label_dir / (name + ".txt")
        shutil.copy2(label_path, dst_label_path)
    else:
        # 健康叶：创建空标注文件
        dst_label_path = dst_label_dir / (name + ".txt")
        dst_label_path.write_text("", encoding="utf-8")


def merge_selfcollect(src_dir: Path, dst_dir: Path) -> dict:
    """合并自采数据到目标数据集。

    Args:
        src_dir: 自采数据目录（按类别分子目录）
        dst_dir: 目标数据集目录（dataset/pomelo_yolo）

    Returns:
        统计报告字典
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)

    if not src_dir.exists():
        print(f"[错误] 自采数据目录不存在：{src_dir}")
        sys.exit(1)

    if not dst_dir.exists():
        print(f"[错误] 目标数据集目录不存在：{dst_dir}")
        sys.exit(1)

    # 统计
    stats = {
        "total_images": 0,
        "per_class": {},
        "per_split": {"train": 0, "val": 0, "test": 0},
    }

    # 遍历每个类别目录
    for class_name in CLASS_NAMES:
        class_dir = src_dir / class_name
        if not class_dir.exists():
            print(f"[警告] 类别目录不存在：{class_dir}")
            continue

        # 获取图片文件
        image_files = _get_image_files(class_dir)
        if not image_files:
            print(f"[警告] 类别目录为空：{class_dir}")
            continue

        # 切分
        total = len(image_files)
        splits = _split_indices(total)

        # 统计
        stats["per_class"][class_name] = {
            "total": total,
            "train": len(splits["train"]),
            "val": len(splits["val"]),
            "test": len(splits["test"]),
        }
        stats["total_images"] += total

        # 复制文件
        for split_name, indices in splits.items():
            for idx in indices:
                image_path = image_files[idx]
                new_name = f"{class_name}_{image_path.stem}"
                _copy_image_and_label(image_path, dst_dir, split_name, new_name)
                stats["per_split"][split_name] += 1

        print(f"[合并] {class_name}: {total} 张（train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])}）")

    # 更新 citrus.yaml
    _update_citrus_yaml(dst_dir)

    # 生成统计报告
    _write_stats_report(dst_dir, stats)

    return stats


def _update_citrus_yaml(dst_dir: Path) -> None:
    """更新 citrus.yaml 中的路径。"""
    yaml_path = dst_dir / "citrus.yaml"
    if not yaml_path.exists():
        return

    content = yaml_path.read_text(encoding="utf-8")
    # 替换路径为绝对路径（相对于数据集目录）
    content = content.replace(
        "E:/柚子病虫害AI识别/dataset/pomelo_yolo",
        str(dst_dir)
    )
    yaml_path.write_text(content, encoding="utf-8")
    print(f"[更新] citrus.yaml 路径已更新为：{dst_dir}")


def _write_stats_report(dst_dir: Path, stats: dict) -> None:
    """写入统计报告。"""
    report_path = dst_dir / "dataset_stats.txt"
    lines = [
        "数据集统计报告",
        "=" * 50,
        f"总图片数：{stats['total_images']}",
        "",
        "按类别统计：",
    ]

    for class_name, class_stats in stats["per_class"].items():
        lines.append(f"  {class_name}：{class_stats['total']} 张")
        lines.append(f"    train={class_stats['train']}, val={class_stats['val']}, test={class_stats['test']}")

    lines.append("")
    lines.append("按切分统计：")
    lines.append(f"  train：{stats['per_split']['train']} 张")
    lines.append(f"  val：{stats['per_split']['val']} 张")
    lines.append(f"  test：{stats['per_split']['test']} 张")

    lines.append("")
    lines.append("=" * 50)
    lines.append(f"切分比例：train={TRAIN_RATIO}, val={VAL_RATIO}, test={TEST_RATIO}")
    lines.append(f"随机种子：{SEED}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[报告] 统计报告已写入：{report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="合并自采数据到数据集",
    )
    parser.add_argument(
        "--src",
        type=Path,
        required=True,
        help="自采数据目录（按类别分子目录）",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        required=True,
        help="目标数据集目录（dataset/pomelo_yolo）",
    )
    args = parser.parse_args()

    print(f"[合并] 自采数据目录：{args.src}")
    print(f"[合并] 目标数据集目录：{args.dst}")
    print()

    stats = merge_selfcollect(args.src, args.dst)

    print()
    print("=" * 50)
    print(f"[完成] 共合并 {stats['total_images']} 张图片")
    print(f"[完成] train={stats['per_split']['train']}, val={stats['per_split']['val']}, test={stats['per_split']['test']}")
    print("=" * 50)


if __name__ == "__main__":
    main()