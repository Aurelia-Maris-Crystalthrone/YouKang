"""类别映射表唯一口径（4 类检测体系 + 负样本集合 + 端云共用阈值常量）。

全部交付物（数据准备/合并脚本、在线服务打包副本、端侧后处理参考实现）
统一引用本文件，禁止各处自行维护类别定义（spec DFX 4.4-2）。

体系变更说明（2026-10-27，基于真实数据统计后重构）：

1. healthy 由检测类降为**负样本**。
   原因：healthy 无真实检测框（Roboflow 集不含该类，CLP-14 仅有分类图），
   作为检测类只能用整图伪框，会导致一张病叶同时输出 canker 小框
   与 healthy 整图框 的自相矛盾结果，画框演示直接穿帮。
   标准做法：healthy 图片以**空标注文件**参与训练，
   推理时无检测框即判定健康（业务层映射为 HEALTHY_LABEL）。

2. 新增 greening（黄龙病）为检测类，提前于原计划的二期。
   依据：Roboflow 检测集中 greening 实有 2946 张真框
   （文件名前缀 Greening_ 900 张 + IMG_ 2046 张，均为类别 id 3），
   是全数据集最大类；CLP-14 另有 Deficiency Leaf（缺素）181 张作负样本。
   二者配对正好正面回应项目痛点：黄龙病常被误判为缺素症。

3. 负样本集合覆盖全部易误判非目标类
   （煤污 / 黑斑 / 脂点黄斑 / 卷叶 / 枯叶 / 缺素），约 5000 张，
   用于抑制误报、提升拒识（OOD）能力。

类别编号一经确定禁止调整；二期扩展仅允许在 CLASS_NAMES 末尾追加。
"""
from typing import Optional

# 检测类（模型输出顺序，编号即 class id）
#   0 red_spider_mite  整图伪框：虫体约 0.5mm，640 输入不可见，检测目标为全叶受害症状
#   1 anthracnose      真框 708（Roboflow）+ 伪框（CLP-14）
#   2 canker           真框 489（Roboflow）+ 伪框（CLP-14）
#   3 greening         真框 2946（Roboflow）；检疫性病害，输出须带上报提示
CLASS_NAMES: tuple = ("red_spider_mite", "anthracnose", "canker", "greening")

# 业务层标签：模型无检测框时输出该结论（不参与模型类别编号）
HEALTHY_LABEL: str = "healthy"

# 端云同口径阈值。置信度 0.25 为 YOLOv5 常用值；
# 原 0.45 作用在 obj×cls 乘积上，会大量漏检小病斑。
CONF_THRESHOLD: float = 0.25
IOU_THRESHOLD: float = 0.45

_ALIAS_RULES: dict = {
    "red_spider_mite": "red_spider_mite",
    "spider_mites": "red_spider_mite",
    "spider_mite": "red_spider_mite",
    "citrus_mite": "red_spider_mite",
    "citrus_red_mite": "red_spider_mite",
    "anthracnose": "anthracnose",
    "antracnose": "anthracnose",
    "canker": "canker",
    "citrus_canker": "canker",
    "greening": "greening",
    "citrus_greening": "greening",
    "huanglongbing": "greening",
    "hlb": "greening",
}

# 负样本类别：图片纳入训练，但生成**空标注文件**（无检测框）。
# 来源为 CLP-14 与 Roboflow 中易与目标病害混淆的非目标类：
# 缺素 / 煤污 / 黑斑 / 脂点黄斑 / 卷叶 / 枯叶 / 细菌性叶枯。
# 其中"缺素"最关键：它是黄龙病最主要的误判对象（见上方说明 2）。
# 纳入后可显著提升模型拒识能力：非目标类不再被强行报成病害。
_NEGATIVE_ALIASES: set = {
    "healthy",
    "deficiency_leaf",
    "black_spot",
    "melanose",
    "sooty_mould",
    "sooty_mold",
    "dry_leaf",
    "curl_leaf",
    "curl_virus",
    "bacterial_blight",
    "greasy_spot",
}

_NAME_TO_ID: dict = {name: idx for idx, name in enumerate(CLASS_NAMES)}


def _canonical_key(name: str) -> Optional[str]:
    """大小写不敏感；空格与连字符统一为下划线。非字符串返回 None。"""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace("-", "_")
    return "_".join(key.split())


def normalize_class_name(name: str) -> Optional[int]:
    """将类别名（目录名/标注名）归一化为检测类编号。

    命中负样本集合或未知类别返回 None（调用方据此丢弃或作负样本），不抛异常。
    """
    key = _canonical_key(name)
    if key is None:
        return None
    canonical = _ALIAS_RULES.get(key)
    if canonical is None:
        return None
    return _NAME_TO_ID[canonical]


def is_negative_class(name: str) -> bool:
    """是否为负样本类别（健康叶或易误判的非目标类）。

    负样本图片纳入训练集但不生成检测框；用于降低误报、提升拒识能力。
    """
    key = _canonical_key(name)
    return key is not None and key in _NEGATIVE_ALIASES
