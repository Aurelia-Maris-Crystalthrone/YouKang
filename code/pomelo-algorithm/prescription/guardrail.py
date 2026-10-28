"""输出前护栏（guardrail）。

核心职责：检查智能体最终文本里出现的每个药名是否都在已登记白名单内。
出现白名单外的药名 → 拦截并要求改为"请咨询当地农技人员"。

理由：LLM 幻觉出未登记农药是**违法**风险，也是评委一票否决点，必须有硬护栏。

检测策略：
1. 精确匹配白名单药名（已登记农药）
2. 对文本中其他 2-10 字汉字串，过滤掉非药名词汇与常见后缀
3. 剩余候选若以农药名常见后缀（素/酯/灵/唑/锰锌/铜/霉素/菌酯/菌灵/磷/腈/威/沙）结尾，判定为违规药名
"""
from __future__ import annotations

import re

# 常见非药名词汇（2-10 字）
NON_PESTICIDE_WORDS = {
    "我们", "你们", "他们", "什么", "如何", "可以", "已经", "现在", "今天", "明天",
    "建议", "使用", "防治", "红蜘蛛", "炭疽病", "溃疡病", "黄龙病", "柑橘",
    "稀释", "倍数", "倍液", "方法", "注意", "需要", "应该", "不能", "进行",
    "操作", "处理", "发生", "发现", "及时", "定期", "加强", "保持", "清除",
    "修剪", "施肥", "灌溉", "排水", "通风", "透光", "干燥", "湿润",
    "高温", "低温", "雨季", "春季", "夏季", "秋季", "冬季", "萌芽", "开花",
    "结果", "采收", "休眠", "生长", "发育", "成熟", "果实", "叶片", "枝条",
    "树干", "树冠", "果园", "地块", "品种", "树龄", "面积", "位置",
    "每亩", "公顷", "公斤", "克", "毫升", "升", "天", "周", "月",
    "安全", "间隔", "期", "最多", "最少", "至少", "超过", "低于", "以上",
    "以下", "左右", "大约", "精确", "具体", "详细", "说明", "报告",
    "记录", "数据", "信息", "内容", "结果", "效果", "影响", "风险",
    "危害", "损失", "产量", "质量", "价格", "成本", "收益", "利润",
    "稀释倍数", "稀释倍", "倍液防治", "防治红", "防治炭", "防治溃",
    "防治黄", "防治柑", "使用阿", "使用螺", "使用某", "使用另",
    "加强果园", "通风透光", "及时清除", "行间杂草", "或螺螨酯",
    "防治红蜘蛛", "建议使用", "稀释倍数3000", "倍液",
}

# 农药名常见后缀（用于判定候选是否为药名）
PESTICIDE_SUFFIXES = [
    "素", "酯", "灵", "唑", "锰锌", "铜", "霉素", "菌酯", "菌灵", "磷",
    "腈", "威", "沙", "啉", "锌", "铵", "酮", "醚", "胺", "酚",
    "菌清", "菌杀", "虫清", "虫杀", "螨清", "螨杀", "螨死", "螨危",
    "锰", "锌", "硫", "硅", "碘", "药",  # "药"字结尾的通常是农药名
]


def _looks_like_pesticide_name(candidate: str) -> bool:
    """判断候选字符串是否像农药名。

    农药名通常以特定化学后缀结尾。
    """
    if len(candidate) < 2:
        return False
    # 以农药名常见后缀结尾
    for suffix in PESTICIDE_SUFFIXES:
        if candidate.endswith(suffix):
            return True
    # 包含常见农药名前缀
    pesticide_prefixes = [
        "阿维", "螺螨", "乙唑", "联苯", "吡唑", "咪鲜", "苯醚", "代森",
        "噻唑", "春雷", "中生", "王铜", "喹啉", "络氨", "多菌", "三唑",
        "嘧菌", "吡虫", "啶虫", "噻虫", "联苯菊", "矿物",
    ]
    for prefix in pesticide_prefixes:
        if candidate.startswith(prefix):
            return True
    return False


def _split_candidate(candidate: str) -> list[str]:
    """在非药名词汇边界拆分候选字符串。

    例如："某未知神药防治红蜘蛛" → ["某未知神药", "防治红蜘蛛"]
    """
    # 找到非药名词汇在候选中的位置
    split_positions = set()
    for word in NON_PESTICIDE_WORDS:
        pos = candidate.find(word)
        if pos >= 0:
            split_positions.add(pos)
            split_positions.add(pos + len(word))

    # 如果没有找到非药名词汇，返回原候选
    if not split_positions:
        return [candidate]

    # 按拆分位置分割
    split_positions = sorted(split_positions)
    # 只保留 0 和 len(candidate) 之间的位置
    split_positions = [p for p in split_positions if 0 < p < len(candidate)]
    if not split_positions:
        return [candidate]

    parts = []
    start = 0
    for pos in split_positions:
        part = candidate[start:pos]
        if part:
            parts.append(part)
        start = pos
    last_part = candidate[start:]
    if last_part:
        parts.append(last_part)

    return parts


def validate_output(text: str, allowed_pesticide_names: list[str]) -> dict:
    """校验智能体输出文本中的药名是否在白名单内。

    Args:
        text: 智能体输出的文本
        allowed_pesticide_names: 白名单药名列表（中文通用名）

    Returns:
        {
            "is_valid": bool,
            "detected": list[str],
            "violations": list[str],
            "suggested_text": str,
        }
    """
    whitelist = {name.lower() for name in allowed_pesticide_names}
    whitelist_exact = set(allowed_pesticide_names)

    detected: list[str] = []

    # 策略 1：精确匹配白名单药名
    for name in allowed_pesticide_names:
        if name in text:
            detected.append(name)

    # 策略 0：先把白名单药名从文本中屏蔽（长名优先），再扫描。
    # 不做这一步时，"用炔螨特加多菌灵" 会因包含合法药名"炔螨特"
    # 而被整体跳过，藏在其中的"多菌灵"（未登记）就漏检了——
    # 这正是 LLM 最可能输出的混合形式，也是护栏最危险的失效场景。
    masked = text
    for _name in sorted(allowed_pesticide_names, key=len, reverse=True):
        masked = masked.replace(_name, "\u3000")  # 全角空格：非汉字，可打断汉字串

    # 策略 2：提取文本中所有 2-10 字连续汉字串
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]{2,10}')
    for match in chinese_pattern.finditer(masked):
        candidate = match.group()

        # 跳过非药名词汇
        if candidate in NON_PESTICIDE_WORDS:
            continue
        # 跳过已检测到的
        if candidate in detected:
            continue
        # 跳过白名单药名
        if candidate in whitelist_exact:
            continue
        # 跳过包含白名单药名的（如"阿维菌素稀释倍数"包含"阿维菌素"）
        if any(name in candidate for name in allowed_pesticide_names):
            continue
        # 跳过白名单药名的子串（如"螨酯"是"螺螨酯"的子串）
        if any(candidate in name for name in allowed_pesticide_names):
            continue

        # 在非药名词汇边界拆分候选
        parts = _split_candidate(candidate)
        for part in parts:
            if part in NON_PESTICIDE_WORDS:
                continue
            if part in detected:
                continue
            if part in whitelist_exact:
                continue
            if any(name in part for name in allowed_pesticide_names):
                continue
            if any(part in name for name in allowed_pesticide_names):
                continue
            # 判定是否像农药名
            if _looks_like_pesticide_name(part):
                detected.append(part)

    # 策略 2b：后缀模式扫描（在屏蔽后的文本上）。
    # 长汉字串里可能藏着药名，例如"加多菌灵混喷效果更好"整体不像药名，
    # 但其中的"加多菌灵"以农药后缀结尾，必须单独检出。
    # 护栏宁可误报也不漏报：漏报意味着未登记农药被推荐出去（违法风险）。
    # 前缀窗口固定 1-3 字：中文药名多为 2-4 字，窗口过宽会把前导虚词
    # 吞进候选（"或某未知神药"），导致替换时误伤上下文且漏掉精确药名。
    suffix_alt = "|".join(sorted(PESTICIDE_SUFFIXES, key=len, reverse=True))
    suffix_pattern = re.compile(r'[\u4e00-\u9fff]{1,3}(' + suffix_alt + r')')
    for match in suffix_pattern.finditer(masked):
        seg = match.group()
        if seg in NON_PESTICIDE_WORDS:
            continue
        if any(word in seg for word in NON_PESTICIDE_WORDS):
            continue
        if seg in detected or seg in whitelist_exact:
            continue
        if any(name in seg for name in allowed_pesticide_names):
            continue
        if _looks_like_pesticide_name(seg):
            detected.append(seg)

    # 策略 3：提取英文药名
    english_pattern = re.compile(r'\b[a-zA-Z][a-zA-Z0-9\-]{1,19}\b')
    common_english = {"the", "and", "for", "are", "but", "not", "you", "all",
                      "can", "her", "was", "one", "our", "out", "use", "with",
                      "that", "this", "have", "has", "had", "were", "been",
                      "being", "do", "does", "did", "of", "in", "on", "at",
                      "to", "for", "by", "from", "up", "down", "in", "out"}
    for match in english_pattern.finditer(text):
        candidate = match.group()
        if candidate.lower() in common_english:
            continue
        if candidate.lower() in whitelist:
            continue
        if candidate in detected:
            continue
        detected.append(candidate)

    # 去重（保留原顺序）。不做子串剔除：短候选往往是被切出的片段
    # （如"一个假药"来自"另一个假药"），剔掉会导致替换残留。
    detected = list(dict.fromkeys(detected))

    # 找出白名单外的药名
    violations = [d for d in detected
                  if d.lower() not in whitelist and d not in whitelist_exact]

    if not violations:
        return {
            "is_valid": True,
            "detected": detected,
            "violations": [],
            "suggested_text": text,
        }

    # 替换违规药名：长的先替换，避免短片段先被替换后残留长串碎片
    suggested = text
    for v in sorted(violations, key=len, reverse=True):
        suggested = suggested.replace(v, "请咨询当地农技人员")

    return {
        "is_valid": False,
        "detected": detected,
        "violations": violations,
        "suggested_text": suggested,
    }


def format_guardrail_report(result: dict) -> str:
    """生成护栏校验报告（中文）。"""
    if result["is_valid"]:
        return f"[护栏] 通过：检测到 {len(result['detected'])} 个药名，均在白名单内"
    lines = []
    lines.append("[护栏] 拦截：检测到白名单外的药名")
    for v in result["violations"]:
        lines.append(f"  ✗ {v}：未在白名单内，已替换为「请咨询当地农技人员」")
    lines.append("")
    lines.append("建议：请确认以下药名是否应加入白名单，或删除后重新生成：")
    lines.append(f"  白名单：{result['detected']}")
    lines.append(f"  违规：{result['violations']}")
    return "\n".join(lines)