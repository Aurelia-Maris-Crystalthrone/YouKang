"""Roboflow 检测集合并脚本（可选，spec 5.1.1-7，design 接口 2）。

将 Roboflow 导出的 YOLOv5 格式数据集（data.yaml + train/valid/test）合并进
已生成的目标数据集：
1. 读取 data.yaml 的 names 建立 id→类别名映射，仅保留可映射至 4 类体系的标注行
  （canker/healthy 直接映射；拼写变体 antracnose 经别名归一化映射至 anthracnose；
   其余类别标注行全部丢弃）；
2. 多边形 segment 标注转换为外接边界框五值归一化格式（与整图伪框一致）；
3. 图片与标签以 rf_ 前缀重命名、同步复制入 dst（源目录只读，防冲突）；
4. 无有效标注的图片不纳入输出；
5. 重新输出统计报告（打印 + 更新 dataset_stats.txt，含 rf_ 来源计数）。
仅依赖 Python 标准库。

用法：
    python merge_roboflow.py --rf-src "<Roboflow导出目录>" --dst "<已生成的YOLOv5数据集目录>"
"""
import argparse
import shutil
import sys
from pathlib import Path

from labelmap import CLASS_NAMES, normalize_class_name
from prepare_dataset import render_stats

RF_PREFIX: str = "rf_"
RF_SPLIT_MAP: dict = {"train": "train", "valid": "val", "test": "test"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def parse_data_yaml(path: Path) -> dict:
    """解析 data.yaml 的 names（兼容列表式与数字键 dict 式）。"""
    names: dict = {}
    in_names_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("names:"):
            rest = stripped[len("names:"):].strip()
            in_names_block = False
            if rest.startswith("[") and rest.endswith("]"):
                items = [x.strip().strip("'\"") for x in rest[1:-1].split(",") if x.strip()]
                names = {i: n for i, n in enumerate(items)}
            elif not rest:
                in_names_block = True
            continue
        if in_names_block:
            head, _, tail = stripped.partition(":")
            if head.strip().isdigit():
                names[int(head.strip())] = tail.strip().strip("'\"")
            else:
                in_names_block = False
    return names


def parse_annotation_line(line: str, id_to_name: dict):
    """解析单条标注：bbox 五值或 segment 多边形 → (class_id, (xc, yc, w, h))。

    类别 id → 类别名 → labelmap 别名归一化；不可映射返回 None（丢弃）。
    """
    tokens = line.split()
    if len(tokens) < 5:
        return None
    try:
        raw_id = int(float(tokens[0]))
        coords = [float(t) for t in tokens[1:]]
    except ValueError:
        return None
    name = id_to_name.get(raw_id)
    if name is None:
        return None
    class_id = normalize_class_name(name)
    if class_id is None:
        return None
    if len(coords) == 4:
        xc, yc, w, h = coords
    elif len(coords) % 2 == 0 and len(coords) >= 4:
        xs, ys = coords[0::2], coords[1::2]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        xc, yc = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        w, h = xmax - xmin, ymax - ymin
    else:
        return None
    xc = min(max(xc, 0.0), 1.0)
    yc = min(max(yc, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0)
    h = min(max(h, 0.0), 1.0)
    return class_id, (xc, yc, w, h)


def convert_label_file(lbl_path: Path, id_to_name: dict) -> list:
    """读取标注文件逐行转换过滤，返回保留的标注行列表。"""
    kept = []
    for line in lbl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = parse_annotation_line(line, id_to_name)
        if parsed is None:
            continue
        class_id, (xc, yc, w, h) = parsed
        kept.append(f"{class_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    return kept


def locate_images_dir(rf_split_dir: Path) -> Path | None:
    for cand in (rf_split_dir / "images", rf_split_dir):
        if cand.is_dir():
            imgs = [p for p in cand.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            if imgs:
                return cand
    return None


def locate_labels_dir(rf_split_dir: Path) -> Path:
    return rf_split_dir / "labels" if (rf_split_dir / "labels").is_dir() else rf_split_dir


def validate_dst(dst: Path) -> bool:
    """校验 dst 为 prepare_dataset.py 已生成的 YOLOv5 标准结构（spec 5.1.3-5）。"""
    return all((dst / part / split).is_dir()
               for part in ("images", "labels")
               for split in ("train", "val", "test"))


def first_class_id(lbl_path: Path) -> int | None:
    try:
        for line in lbl_path.read_text(encoding="utf-8").splitlines():
            head = line.strip().split(" ")[0]
            if head.isdigit():
                cid = int(head)
                if 0 <= cid < len(CLASS_NAMES):
                    return cid
                return None
    except OSError:
        return None
    return None


def scan_dataset_stats(dst: Path) -> tuple:
    """扫描 dst 全数据集：每类每 split 图片数 + rf_ 来源计数（spec 5.1.1-7.7）。"""
    per_class = {name: {s: 0 for s in ("train", "val", "test")} for name in CLASS_NAMES}
    rf_count = {name: {s: 0 for s in ("train", "val", "test")} for name in CLASS_NAMES}
    for split in ("train", "val", "test"):
        img_dir = dst / "images" / split
        lbl_dir = dst / "labels" / split
        for img in sorted(img_dir.iterdir()):
            if not img.is_file():
                continue
            lbl = lbl_dir / f"{img.stem}.txt"
            if not lbl.is_file():
                continue
            cid = first_class_id(lbl)
            if cid is None:
                continue
            per_class[CLASS_NAMES[cid]][split] += 1
            if img.name.startswith(RF_PREFIX):
                rf_count[CLASS_NAMES[cid]][split] += 1
    return per_class, rf_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Roboflow 检测集合并（rf_ 前缀，源只读）")
    parser.add_argument("--rf-src", required=True, help="Roboflow 导出根目录（含 data.yaml）")
    parser.add_argument("--dst", required=True, help="已生成的 YOLOv5 数据集根目录")
    args = parser.parse_args()

    rf_src = Path(args.rf_src)
    dst = Path(args.dst)

    data_yaml = rf_src / "data.yaml"
    if not rf_src.is_dir() or not data_yaml.is_file():
        print(f"[合并] 报错：rf-src 路径无效或缺 data.yaml: {rf_src}")
        return 2

    id_to_name = parse_data_yaml(data_yaml)
    if not id_to_name:
        print(f"[合并] 报错：data.yaml 中未解析到 names 类别配置: {data_yaml}")
        return 2

    if not dst.is_dir() or not validate_dst(dst):
        print(f"[合并] 报错：dst 缺少 YOLOv5 标准目录结构，请先执行数据准备: {dst}")
        return 2

    merged_images = 0
    merged_lines = 0
    skipped_splits: list = []
    for rf_split, target_split in RF_SPLIT_MAP.items():
        rf_split_dir = rf_src / rf_split
        if not rf_split_dir.is_dir():
            skipped_splits.append(rf_split)
            continue
        img_dir = locate_images_dir(rf_split_dir)
        if img_dir is None:
            skipped_splits.append(rf_split)
            continue
        lbl_dir = locate_labels_dir(rf_split_dir)
        out_img_dir = dst / "images" / target_split
        out_lbl_dir = dst / "labels" / target_split
        for img in sorted(img_dir.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            lbl = lbl_dir / f"{img.stem}.txt"
            if not lbl.is_file():
                continue
            kept = convert_label_file(lbl, id_to_name)
            if not kept:
                continue
            new_img_name = RF_PREFIX + img.name
            new_lbl_name = RF_PREFIX + img.stem + ".txt"
            if (out_img_dir / new_img_name).exists() or (out_lbl_dir / new_lbl_name).exists():
                continue
            shutil.copy2(img, out_img_dir / new_img_name)
            (out_lbl_dir / new_lbl_name).write_text("\n".join(kept) + "\n", encoding="utf-8")
            merged_images += 1
            merged_lines += len(kept)

    per_class, rf_count = scan_dataset_stats(dst)

    text = render_stats(per_class, "统计报告（Roboflow 合并后重新输出）",
                        rf_stats=rf_count, skipped_splits=skipped_splits)
    print(f"[合并] 本次合并: {merged_images} 张图片 / {merged_lines} 条标注行（rf_ 前缀）")
    print(text)
    (dst / "dataset_stats.txt").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())