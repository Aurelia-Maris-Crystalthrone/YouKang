"""统一数据集构建脚本：CLP-14（分类）+ Roboflow（检测真框）→ 可训练 YOLOv5 数据集。

解决的问题（2026-10-27 评审 P0）：
    1. Roboflow 集 6021 张图全在 train/，valid/ test/ 目录不存在 → 无法评估；
    2. 4 类体系里 red_spider_mite 与 healthy 无真实检测框；
    3. 无难负样本，模型对非目标类（缺素/黄龙/煤污）会强行报病害。

处理规则：
    - CLP-14（分类图）：目标类 → 整图伪框；负样本类 → **空标注文件**。
      保留 CLP-14 官方 train/val/test 划分，避免数据泄漏。
    - Roboflow（检测图）：仅保留可映射至 3 类的标注行，按 8:1:1 随机切分
      （种子 42），图片加 rf_ 前缀防冲突。
    - 输出标准 YOLOv5 结构 + citrus.yaml（绝对路径）+ dataset_stats.txt。

仅依赖 Python 标准库。

用法：
    python build_dataset.py \
      --clp "E:/柚子病虫害AI识别/archive/CitrusLeafPathology-14/CitrusLeafPathology-14" \
      --rf  "E:/柚子病虫害AI识别/citrus-leaf-disease-2.v1-test1.yolov5pytorch" \
      --dst "E:/柚子病虫害AI识别/dataset/pomelo_yolo"
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
RF_PREFIX: str = "rf_"
RF_SPLIT_MAP: dict = {"train": "train", "valid": "val", "test": "test"}


# ---------------------------------------------------------------- CLP-14 部分

def parse_data_yaml(path: Path) -> dict:
    """解析 Roboflow data.yaml 的 names（兼容列表式与数字键 dict 式）。"""
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
    """解析标注行：bbox 五值或 segment 多边形 → (class_id, (xc, yc, w, h))。"""
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
    clamp = lambda v: min(max(v, 0.0), 1.0)  # noqa: E731
    return class_id, (clamp(xc), clamp(yc), clamp(w), clamp(h))


def convert_label_file(lbl_path: Path, id_to_name: dict) -> list:
    """逐行转换过滤标注文件，返回保留的标注行。"""
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


def _unique_stem(img_dir: Path, stem: str, suffix: str) -> str:
    """目标同名冲突时追加序号，保证图片与标签使用同一 stem。"""
    if not (img_dir / f"{stem}{suffix}").exists():
        return stem
    i = 1
    while True:
        cand = f"{stem}_{i}"
        if not (img_dir / f"{cand}{suffix}").exists():
            return cand
        i += 1


def emit(dst: Path, split_dirs: dict, img: Path, lines: list, stem: str) -> bool:
    """写入一张图片及其标注（lines 为空即负样本空标注）。"""
    img_dir = dst / "images" / split_dirs["images"]
    lbl_dir = dst / "labels" / split_dirs["images"]
    suffix = img.suffix.lower()
    final_stem = _unique_stem(img_dir, stem, suffix)
    try:
        shutil.copy2(img, img_dir / f"{final_stem}{suffix}")
    except OSError as exc:
        print(f"[构建] 跳过（复制失败）{img.name}: {exc}")
        return False
    (lbl_dir / f"{final_stem}.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return True


def build_from_clp(clp_root: Path, dst: Path, counter: dict) -> list:
    """处理 CLP-14 分类集：目标类整图伪框，负样本类空标注。保留官方划分。"""
    dropped: list = []
    for split in SPLITS:
        split_dir = clp_root / split
        if not split_dir.is_dir():
            dropped.append(f"CLP-14 缺失 split: {split}")
            continue
        for cls_dir in sorted(split_dir.iterdir()):
            if not cls_dir.is_dir():
                continue
            class_id = normalize_class_name(cls_dir.name)
            negative = is_negative_class(cls_dir.name)
            if class_id is None and not negative:
                if cls_dir.name not in dropped:
                    dropped.append(f"未映射类别: {cls_dir.name}")
                continue
            for img in sorted(cls_dir.iterdir()):
                if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                    continue
                if class_id is not None:
                    lines = [f"{class_id} 0.5 0.5 1.0 1.0"]
                    bucket = CLASS_NAMES[class_id]
                else:
                    lines = []
                    bucket = "__negative__"
                if emit(dst, {"images": split}, img, lines,
                        f"{bucket}_{img.stem}"):
                    counter[bucket][split] += 1
    return dropped


def build_from_roboflow(rf_root: Path, dst: Path, counter: dict) -> list:
    """处理 Roboflow 检测集：真框，8:1:1 随机切分（种子 42）。"""
    notes: list = []
    data_yaml = rf_root / "data.yaml"
    if not data_yaml.is_file():
        return ["Roboflow 缺少 data.yaml，已跳过"]
    id_to_name = parse_data_yaml(data_yaml)
    if not id_to_name:
        return ["Roboflow data.yaml 未解析到 names，已跳过"]

    # 收集所有可映射图片（Roboflow v1 全部在 train/）
    pool: list = []
    for rf_split in RF_SPLIT_MAP:
        rf_split_dir = rf_root / rf_split
        if not rf_split_dir.is_dir():
            continue
        img_dir = rf_split_dir / "images" if (rf_split_dir / "images").is_dir() else rf_split_dir
        lbl_dir = rf_split_dir / "labels" if (rf_split_dir / "labels").is_dir() else rf_split_dir
        for img in sorted(img_dir.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMAGE_EXTS:
                continue
            lbl = lbl_dir / f"{img.stem}.txt"
            if not lbl.is_file():
                continue
            kept = convert_label_file(lbl, id_to_name)
            if not kept:
                continue
            pool.append((img, kept))
    if not pool:
        return ["Roboflow 无可映射标注，已跳过"]

    rng = random.Random(SEED)
    rng.shuffle(pool)
    n = len(pool)
    n_test = int(n * 0.1)
    n_val = int(n * 0.1)
    buckets = {
        "train": pool[n_test + n_val:],
        "val": pool[n_test:n_test + n_val],
        "test": pool[:n_test],
    }
    for split, items in buckets.items():
        for img, kept in items:
            first_id = int(kept[0].split()[0])
            if emit(dst, {"images": split}, img, kept, f"{RF_PREFIX}{img.stem}"):
                counter[CLASS_NAMES[first_id]][split] += 1
    notes.append(f"Roboflow 切分: train={len(buckets['train'])} "
                 f"val={len(buckets['val'])} test={len(buckets['test'])}")
    return notes


# ------------------------------------------------------------------ 输出部分

def write_citrus_yaml(dst: Path) -> None:
    """生成 citrus.yaml（绝对路径，nc=3）。"""
    root = str(dst.resolve()).replace("\\", "/")
    names = ", ".join(f"'{n}'" for n in CLASS_NAMES)
    content = (
        "# YOLOv5 dataset config - pomelo disease detection\n"
        "# 由 build_dataset.py 自动生成；healthy 为负样本（空标注，不占类别编号）\n"
        f"train: {root}/images/train\n"
        f"val: {root}/images/val\n"
        f"test: {root}/images/test\n"
        "\n"
        f"nc: {len(CLASS_NAMES)}\n"
        f"names: [{names}]\n"
    )
    (dst / "citrus.yaml").write_text(content, encoding="utf-8")


def render_stats(counter: dict, notes: list) -> str:
    lines = ["统计报告（build_dataset.py 生成）",
             f"{'class':<24}{'train':>8}{'val':>8}{'test':>8}{'total':>8}"]
    total = {s: 0 for s in SPLITS}
    for name in list(CLASS_NAMES) + ["__negative__"]:
        row = f"{name:<24}"
        for s in SPLITS:
            row += f"{counter[name][s]:>8}"
            total[s] += counter[name][s]
        row += f"{sum(counter[name].values()):>8}"
        lines.append(row)
    lines.append(f"{'TOTAL':<24}" + "".join(f"{total[s]:>8}" for s in SPLITS)
                 + f"{sum(total.values()):>8}")
    lines.append("")
    lines.append("说明：")
    lines.append("  · __negative__ = 健康叶与易误判非目标类（空标注），"
                 "推理时'无检测框'即判为健康")
    lines.append("  · red_spider_mite 为整图伪框：红蜘蛛虫体约 0.5mm，"
                 "640×640 输入不可见，检测目标为'全叶受害症状'（有农学依据）")
    for note in notes:
        lines.append(f"  · {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="构建柚子病虫害 YOLOv5 数据集（CLP-14 + Roboflow）")
    parser.add_argument("--clp", required=True, help="CLP-14 根目录（含 train/val/test 类目）")
    parser.add_argument("--rf", required=True, help="Roboflow 导出根目录（含 data.yaml）")
    parser.add_argument("--dst", required=True, help="输出数据集根目录")
    args = parser.parse_args()

    clp_root, rf_root, dst = Path(args.clp), Path(args.rf), Path(args.dst)

    if not clp_root.is_dir():
        print(f"[构建] 报错：--clp 路径无效: {clp_root}")
        return 2

    if dst.exists():
        shutil.rmtree(dst)
    for split in SPLITS:
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)

    counter = {name: {s: 0 for s in SPLITS} for name in CLASS_NAMES}
    counter["__negative__"] = {s: 0 for s in SPLITS}

    notes: list = []
    notes += build_from_clp(clp_root, dst, counter)
    if rf_root.is_dir():
        notes += build_from_roboflow(rf_root, dst, counter)
    else:
        notes.append("未找到 Roboflow 目录，已跳过（仅用 CLP-14）")

    write_citrus_yaml(dst)
    text = render_stats(counter, notes)
    print(text)
    (dst / "dataset_stats.txt").write_text(text + "\n", encoding="utf-8")
    print(f"\n[构建] 完成，输出目录: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
