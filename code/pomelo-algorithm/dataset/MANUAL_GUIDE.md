# 柚子病叶图片采集 - 手动操作指南

## 问题说明

沙箱网络受限，无法直接从互联网下载图片。请按以下步骤手动采集。

---

## 方案一：百度图片手动采集（推荐）

### 步骤 1：打开百度图片

浏览器访问：https://image.baidu.com/

### 步骤 2：搜索并保存图片

按以下关键词搜索并保存图片：

| 类别 | 搜索词 | 保存路径 | 数量 |
|------|--------|----------|------|
| 红蜘蛛 | `柚子红蜘蛛 叶背` | `selfcollect/red_spider_mite/` | 50 张 |
| 炭疽病 | `柚子炭疽病 病斑` | `selfcollect/anthracnose/` | 50 张 |
| 溃疡病 | `柚子溃疡病 病斑` | `selfcollect/canker/` | 50 张 |
| 黄龙病 | `柚子黄龙病 黄化` | `selfcollect/greening/` | 50 张 |
| 健康叶 | `柚子 健康叶` | `selfcollect/healthy/` | 50 张 |

### 步骤 3：命名图片

按规范命名：`{类别}_{序号}_{光照}_{角度}.jpg`

示例：
```
red_spider_mite_001_front_back.jpg
anthracnose_002_side_front.jpg
canker_003_back_back.jpg
```

### 步骤 4：检查图片质量

运行检查脚本：
```bash
python dataset/check_images.py
```

---

## 方案二：手机拍摄（最佳）

### 拍摄要求

1. **必须包含叶背特写**：红蜘蛛虫体在叶背
2. **病斑占画面 1/3 以上**
3. **不同光照**：顺光、逆光、阴天、侧光
4. **不同严重度**：初期、中期、重病

### 拍摄步骤

1. 到柚子园拍摄
2. 每类病害拍摄 50-100 张
3. 按规范命名
4. 复制到 `selfcollect/` 目录

---

## 方案三：学术图片库

### PlantVillage

访问：https://plantvillage.psu.edu/topics/citrus-diseases

下载柑橘病害图片，保存到对应目录。

### Google Images

搜索：
- `pomelo red spider mite leaf`
- `pomelo anthracnose leaf`
- `pomelo canker leaf`
- `pomelo greening yellow leaf`

---

## 标注（LabelImg）

```bash
pip install labelimg
labelimg
```

### 标注规则

| 类别 | 标注方式 |
|------|----------|
| 红蜘蛛 | 整图伪框（0 0.5 0.5 1.0 1.0） |
| 炭疽病 | 真框，紧贴病斑 |
| 溃疡病 | 真框，紧贴病斑 |
| 黄龙病 | 整图伪框（0 0.5 0.5 1.0 1.0） |
| 健康叶 | 空 txt 文件 |

---

## 合并到数据集

```bash
python dataset/merge_selfcollect.py \
    --src /path/to/selfcollect \
    --dst /path/to/dataset/pomelo_yolo
```

---

## 跨域退化评测

```bash
python dataset/eval_domain_gap.py \
    --model runs/train/pomelo_v1/weights/best.pt \
    --citrus-dataset /path/to/dataset/pomelo_yolo \
    --pomelo-dataset /path/to/selfcollect \
    --output runs/eval/domain_gap.json
```

---

## 关键提醒

1. **必须包含叶背特写**：红蜘蛛虫体在叶背
2. **病斑占画面 1/3 以上**：否则端侧质量门拒绝
3. **宁可丢弃不乱标**：模糊、存疑图片直接删除
4. **命名规范**：`{类别}_{序号}_{光照}_{角度}.jpg`

---

## 目录结构

```
selfcollect/
├── red_spider_mite/
│   ├── red_spider_mite_001_front_back.jpg
│   └── ...
├── anthracnose/
│   ├── anthracnose_001_side_front.jpg
│   └── ...
├── canker/
│   ├── canker_001_back_back.jpg
│   └── ...
├── greening/
│   ├── greening_001_cloudy_front.jpg
│   └── ...
└── healthy/
    ├── healthy_001_front_front.jpg
    └── ...
```