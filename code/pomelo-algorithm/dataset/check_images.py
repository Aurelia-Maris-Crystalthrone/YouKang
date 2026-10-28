#!/usr/bin/env python3
"""检查下载的图片是否符合要求。

用法：
    python check_images.py
"""
import os
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).parent / "selfcollect"

CLASSES = ["red_spider_mite", "anthracnose", "canker", "greening", "healthy"]


def check_image(image_path):
    """检查单张图片。

    Args:
        image_path: 图片路径

    Returns:
        dict: 检查结果
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            return {
                "valid": True,
                "width": width,
                "height": height,
                "size": os.path.getsize(image_path),
            }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


def main():
    print("=" * 50)
    print("图片质量检查")
    print("=" * 50)

    total = 0
    valid = 0
    invalid = 0

    for class_name in CLASSES:
        class_dir = BASE_DIR / class_name
        if not class_dir.exists():
            print(f"\n[跳过] {class_name}：目录不存在")
            continue

        images = list(class_dir.glob("*.jpg")) + list(class_dir.glob("*.png"))
        print(f"\n[{class_name}] {len(images)} 张图片")

        for image_path in images:
            total += 1
            result = check_image(image_path)

            if result["valid"]:
                valid += 1
                print(f"  ✓ {image_path.name}: {result['width']}x{result['height']}")
            else:
                invalid += 1
                print(f"  ✗ {image_path.name}: {result['error']}")

    print("\n" + "=" * 50)
    print(f"总计：{total} 张图片，{valid} 张有效，{invalid} 张无效")
    print("=" * 50)

    if invalid > 0:
        print("\n建议删除无效图片：")
        for class_name in CLASSES:
            class_dir = BASE_DIR / class_name
            if not class_dir.exists():
                continue
            for image_path in class_dir.glob("*.jpg"):
                result = check_image(image_path)
                if not result["valid"]:
                    print(f"  rm {image_path}")


if __name__ == "__main__":
    main()