# 自采数据目录

## 目录结构

```
selfcollect/
├── red_spider_mite/    # 红蜘蛛
├── anthracnose/        # 炭疽病
├── canker/             # 溃疡病
├── greening/           # 黄龙病
└── healthy/            # 健康叶
```

## 命名规范

```
{类别}_{序号}_{光照}_{角度}.jpg
```

### 类别代码

| 类别 | 代码 |
|------|------|
| 红蜘蛛 | red_spider_mite |
| 炭疽病 | anthracnose |
| 溃疡病 | canker |
| 黄龙病 | greening |
| 健康叶 | healthy |

### 光照代码

| 光照 | 代码 |
|------|------|
| 顺光 | front |
| 逆光 | back |
| 阴天 | cloudy |
| 侧光 | side |

### 角度代码

| 角度 | 代码 |
|------|------|
| 正面 | front |
| 叶背 | back |

### 示例

```
red_spider_mite_001_front_back.jpg    # 红蜘蛛，顺光，叶背
anthracnose_002_side_front.jpg        # 炭疽病，侧光，正面
canker_003_back_back.jpg              # 溃疡病，逆光，叶背
```

## 采集要求

### 数量要求

| 类别 | 最低数量 | 目标数量 |
|------|----------|----------|
| 红蜘蛛 | 100 张 | 200 张 |
| 炭疽病 | 100 张 | 200 张 |
| 溃疡病 | 100 张 | 200 张 |
| 黄龙病 | 100 张 | 200 张 |
| 健康叶 | 100 张 | 200 张 |

### 必须包含

1. **叶背特写**：红蜘蛛虫体在叶背、溃疡病初期在叶背表现油渍状
2. **不同光照**：顺光、逆光、阴天、侧光
3. **不同严重度**：初期、中期、重病
4. **不同叶龄**：嫩叶、老叶

### 质量要求

- 病斑占画面 1/3 以上
- 图像分辨率 ≥ 640×640
- 病斑边缘清晰
- 无过曝/欠曝

## 标注要求

### 使用 LabelImg

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

## 合并到数据集

```bash
python dataset/merge_selfcollect.py \
    --src /path/to/selfcollect \
    --dst /path/to/dataset/pomelo_yolo
```

## 跨域退化评测

```bash
python dataset/eval_domain_gap.py \
    --model runs/train/pomelo_v1/weights/best.pt \
    --citrus-dataset /path/to/dataset/pomelo_yolo \
    --pomelo-dataset /path/to/selfcollect \
    --output runs/eval/domain_gap.json
```