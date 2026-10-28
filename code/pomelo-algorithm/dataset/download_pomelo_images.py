#!/usr/bin/env python3
"""柚子病叶图片下载脚本。

在本地机器上运行此脚本，从百度图片下载柚子病害图片。

用法：
    python download_pomelo_images.py

依赖：
    pip install requests beautifulsoup4
"""
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("请安装依赖：pip install requests beautifulsoup4")
    sys.exit(1)

# 类别配置
CLASSES = {
    "red_spider_mite": "柚子红蜘蛛 叶背",
    "anthracnose": "柚子炭疽病 病斑",
    "canker": "柚子溃疡病 病斑",
    "greening": "柚子黄龙病 黄化",
    "healthy": "柚子 健康叶",
}

# 保存目录
BASE_DIR = Path(__file__).parent / "selfcollect"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://image.baidu.com/",
}


def search_baidu_images(keyword, max_images=20):
    """搜索百度图片并获取图片 URL。

    Args:
        keyword: 搜索关键词
        max_images: 最大图片数量

    Returns:
        图片 URL 列表
    """
    url = f"https://image.baidu.com/search/acjson?tn=resultjson_com&ipn=rj&ct=201326592&is=&fp=result&queryWord={quote(keyword)}&cl=2&lm=-1&ie=utf-8&oe=utf-8&adpicid=&st=-1&z=&ic=0&word={quote(keyword)}&s=&se=&tab=&width=&height=&face=0&istype=2&qc=&nc=1&fr=&expermode=&force=&pn=0&rn={max_images}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        image_urls = []
        if "data" in data:
            for item in data["data"]:
                if "thumbURL" in item:
                    image_urls.append(item["thumbURL"])
                elif "middleURL" in item:
                    image_urls.append(item["middleURL"])
                elif "objURL" in item:
                    image_urls.append(item["objURL"])

        return image_urls[:max_images]
    except Exception as e:
        print(f"  搜索失败：{e}")
        return []


def download_image(url, save_path, timeout=30):
    """下载单张图片。

    Args:
        url: 图片 URL
        save_path: 保存路径
        timeout: 超时时间

    Returns:
        bool: 是否成功
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()

        # 检查是否为图片
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            print(f"  非图片内容：{content_type}")
            return False

        # 保存图片
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(response.content)

        return True
    except Exception as e:
        print(f"  下载失败：{e}")
        return False


def download_class_images(class_name, keyword, max_images=20):
    """下载某类别的图片。

    Args:
        class_name: 类别名称
        keyword: 搜索关键词
        max_images: 最大图片数量

    Returns:
        int: 成功下载的图片数量
    """
    print(f"\n[下载] {class_name}：{keyword}")

    # 创建保存目录
    save_dir = BASE_DIR / class_name
    save_dir.mkdir(parents=True, exist_ok=True)

    # 搜索图片
    print(f"  搜索图片...")
    image_urls = search_baidu_images(keyword, max_images)
    print(f"  找到 {len(image_urls)} 张图片")

    # 下载图片
    success_count = 0
    for i, url in enumerate(image_urls):
        save_path = save_dir / f"{class_name}_{i+1:03d}.jpg"
        print(f"  下载 {i+1}/{len(image_urls)}: {url[:50]}...")

        if download_image(url, save_path):
            success_count += 1
            print(f"    成功：{save_path.name}")
        else:
            print(f"    失败")

        time.sleep(0.5)  # 避免请求过快

    print(f"  完成：成功 {success_count} 张")
    return success_count


def main():
    print("=" * 50)
    print("柚子病叶图片下载脚本")
    print("=" * 50)

    total_success = 0

    for class_name, keyword in CLASSES.items():
        success = download_class_images(class_name, keyword, max_images=20)
        total_success += success

    print("\n" + "=" * 50)
    print(f"下载完成：共成功 {total_success} 张图片")
    print(f"保存目录：{BASE_DIR}")
    print("=" * 50)

    # 输出下一步操作
    print("\n下一步操作：")
    print("1. 使用 LabelImg 标注图片：labelimg")
    print("2. 健康叶创建空 txt 文件")
    print("3. 合并到数据集：python dataset/merge_selfcollect.py --src selfcollect --dst dataset/pomelo_yolo")


if __name__ == "__main__":
    main()