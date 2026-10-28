"""跨域退化评测脚本（eval_domain_gap）。

用"柑橘数据训练的模型"分别在有自采柚子数据的测试集和原测试集上评估，
输出 mAP 对比；补训自采数据后再评一次，输出提升幅度。

这个对比曲线就是答辩的创新性证据："我们发现跨域退化并用自采数据缓解"。

用法：
    python eval_domain_gap.py \
        --model runs/train/pomelo_v1/weights/best.pt \
        --citrus-dataset /path/to/dataset/pomelo_yolo \
        --pomelo-dataset /path/to/selfcollect \
        --output runs/eval/domain_gap.json

输出：
    {
        "citrus_test_map": 0.78,
        "pomelo_test_map": 0.62,
        "domain_gap": 0.16,
        "after_retrain_map": 0.75,
        "improvement": 0.13,
        "per_class": {
            "red_spider_mite": {"citrus": 0.82, "pomelo": 0.55, "after_retrain": 0.78},
            ...
        }
    }
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run_yolo_val(weights: str, data: str, img: int = 640) -> dict:
    """运行 YOLOv5 val.py 并解析输出。

    返回：
        {
            "mAP50": float,
            "mAP50-95": float,
            "per_class": {
                "class_name": {"P": float, "R": float, "mAP50": float, "mAP50-95": float}
            }
        }
    """
    cmd = [
        sys.executable, "val.py",
        "--weights", weights,
        "--data", data,
        "--img", str(img),
        "--task", "val",
        "--save-json",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )

    # 解析 val.py 输出
    output = result.stdout + result.stderr

    # 提取 mAP
    mAP50 = None
    mAP5095 = None
    per_class = {}

    lines = output.splitlines()
    for line in lines:
        # 解析表格行：Class  Images  Instances  P  R  mAP50  mAP50-95
        parts = line.split()
        if len(parts) >= 7:
            try:
                class_name = parts[0]
                if class_name == "all":
                    mAP50 = float(parts[5])
                    mAP5095 = float(parts[6])
                elif class_name in ("red_spider_mite", "anthracnose", "canker", "greening"):
                    per_class[class_name] = {
                        "P": float(parts[3]),
                        "R": float(parts[4]),
                        "mAP50": float(parts[5]),
                        "mAP50-95": float(parts[6]),
                    }
            except (ValueError, IndexError):
                continue

    return {
        "mAP50": mAP50,
        "mAP50-95": mAP5095,
        "per_class": per_class,
    }


def _create_pomelo_test_dataset(
    selfcollect_dir: Path,
    output_dir: Path,
) -> Path:
    """创建柚子测试数据集（仅 test 集）。

    Args:
        selfcollect_dir: 自采数据目录
        output_dir: 输出目录

    Returns:
        citrus.yaml 路径
    """
    output_dir = Path(output_dir)
    images_dir = output_dir / "images" / "test"
    labels_dir = output_dir / "labels" / "test"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    # 复制自采数据到 test 目录
    total = 0
    for class_name in ("red_spider_mite", "anthracnose", "canker", "greening", "healthy"):
        class_dir = selfcollect_dir / class_name
        if not class_dir.exists():
            continue

        for image_path in class_dir.glob("*.jpg"):
            # 复制图片
            dst_image = images_dir / image_path.name
            import shutil
            shutil.copy2(image_path, dst_image)

            # 复制标注文件
            label_path = image_path.with_suffix(".txt")
            if label_path.exists():
                dst_label = labels_dir / label_path.name
                shutil.copy2(label_path, dst_label)

            total += 1

    # 创建 citrus.yaml
    yaml_content = f"""path: {output_dir}
train: images/test
val: images/test
test: images/test

nc: 4
names: ['red_spider_mite', 'anthracnose', 'canker', 'greening']
"""
    yaml_path = output_dir / "citrus.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")

    print(f"[创建] 柚子测试数据集：{total} 张图片")
    return yaml_path


def evaluate_domain_gap(
    model_path: str,
    citrus_dataset: str,
    pomelo_dataset: str,
    output_path: str,
) -> dict:
    """评估跨域退化。

    Args:
        model_path: 模型路径（best.pt）
        citrus_dataset: 柑橘数据集目录
        pomelo_dataset: 柚子自采数据集目录
        output_path: 输出 JSON 路径

    Returns:
        评估结果字典
    """
    model_path = Path(model_path)
    citrus_dataset = Path(citrus_dataset)
    pomelo_dataset = Path(pomelo_dataset)

    # 1. 在柑橘测试集上评估
    print("[评估] 在柑橘测试集上评估...")
    citrus_yaml = citrus_dataset / "citrus.yaml"
    citrus_result = _run_yolo_val(
        weights=str(model_path),
        data=str(citrus_yaml),
    )
    citrus_map = citrus_result["mAP50"]
    print(f"  柑橘测试集 mAP@0.5：{citrus_map}")

    # 2. 在柚子测试集上评估
    print("[评估] 在柚子测试集上评估...")
    pomelo_output = Path(model_path).parent.parent / "eval" / "pomelo_test"
    pomelo_output.mkdir(parents=True, exist_ok=True)
    pomelo_yaml = _create_pomelo_test_dataset(pomelo_dataset, pomelo_output)
    pomelo_result = _run_yolo_val(
        weights=str(model_path),
        data=str(pomelo_yaml),
    )
    pomelo_map = pomelo_result["mAP50"]
    print(f"  柚子测试集 mAP@0.5：{pomelo_map}")

    # 3. 计算跨域退化
    domain_gap = citrus_map - pomelo_map
    print(f"[分析] 跨域退化：{domain_gap}")

    # 4. 补训后评估（需要重新训练模型，此处仅记录）
    # 实际补训需要调用 train_notebook.sh，此处仅输出提示
    print("[提示] 补训自采数据后，重新运行本脚本可评估提升幅度")

    # 5. 生成报告
    report = {
        "citrus_test_map": citrus_map,
        "pomelo_test_map": pomelo_map,
        "domain_gap": domain_gap,
        "after_retrain_map": None,  # 补训后评估
        "improvement": None,
        "per_class": {},
    }

    # 分类别对比
    for class_name in ("red_spider_mite", "anthracnose", "canker", "greening"):
        citrus_class = citrus_result["per_class"].get(class_name, {})
        pomelo_class = pomelo_result["per_class"].get(class_name, {})
        report["per_class"][class_name] = {
            "citrus": citrus_class.get("mAP50"),
            "pomelo": pomelo_class.get("mAP50"),
            "gap": citrus_class.get("mAP50", 0) - pomelo_class.get("mAP50", 0),
        }

    # 保存报告
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[保存] 评估报告：{output_path}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="跨域退化评测",
    )
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="模型路径（best.pt）",
    )
    parser.add_argument(
        "--citrus-dataset",
        type=str,
        required=True,
        help="柑橘数据集目录",
    )
    parser.add_argument(
        "--pomelo-dataset",
        type=str,
        required=True,
        help="柚子自采数据集目录",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="runs/eval/domain_gap.json",
        help="输出 JSON 路径",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("跨域退化评测")
    print("=" * 50)
    print()

    report = evaluate_domain_gap(
        model_path=args.model,
        citrus_dataset=args.citrus_dataset,
        pomelo_dataset=args.pomelo_dataset,
        output_path=args.output,
    )

    print()
    print("=" * 50)
    print("评测结果")
    print("=" * 50)
    print(f"柑橘测试集 mAP@0.5：{report['citrus_test_map']}")
    print(f"柚子测试集 mAP@0.5：{report['pomelo_test_map']}")
    print(f"跨域退化：{report['domain_gap']}")
    print()
    print("分类别对比：")
    for class_name, class_report in report["per_class"].items():
        print(f"  {class_name}：柑橘 {class_report['citrus']} vs 柚子 {class_report['pomelo']}，退化 {class_report['gap']}")
    print("=" * 50)


if __name__ == "__main__":
    main()