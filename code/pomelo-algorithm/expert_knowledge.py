"""专家知识库：月份-病虫害-防治建议唯一口径（纯标准库，离线可用）。

本文件为预防建议与质保方案生成能力的数据层（spec 5.7、design 模块 G）。

=== 类别口径（与 labelmap.py 对齐，nc=4）===
检测类（模型可输出的 4 个类别）：
    red_spider_mite / anthracnose / canker / greening
非检测类（模型永远不会输出）：
    NO_RISK_LABEL = "healthy" —— 语义为「当月无特定病虫害风险期」，
    仅作为农事历占位符使用。模型侧 healthy 已降为负样本，
    推理时"无任何检测框"才判定为健康（见 labelmap.py 体系说明 1）。
    本文件禁止把 healthy 当作可识别的病虫害对待。

=== 月份-病虫害对应依据（柚子种植农事历，spec 6.6）===
    red_spider_mite  主发 6/7/8/9 月（高温干旱期）
    anthracnose      主发 5/6/7/8/9 月（高温高湿期）
    canker           主发 4/5/6/9/10 月（新梢期 + 台风雨后）
    greening         4-10 月（柑橘木虱活跃与新梢抽发期、果实显症期）
                     1/2/3/11/12 月不列入：此时无新梢、木虱不活动，
                     该时段工作已由 GENERAL_ADVICE 的清园与挖除病树覆盖

=== 数据来源与合规（spec 4.3-3、DFX 4.4）===
PEST_ADVICE 中的药剂与稀释倍数为**通用柑橘农技手册参考值**，
并非柚子作物上的农药登记信息。对外输出前必须经农技/植保专家审定，
并核对当地登记情况；未经审定不得作为正式施药方案下发。
每条建议的 data_source 字段必须一同透出，供上层合规护栏校验。
"""
from dataclasses import dataclass

# 非检测类标签：仅表示"当月无特定病虫害风险"，与模型输出类别严格区分
NO_RISK_LABEL: str = "healthy"

# 检疫性病害：检出即须上报，且必须给出上报提示（greening = 柑橘黄龙病）
QUARANTINE_PESTS: frozenset = frozenset({"greening"})

# 通用农技手册参考值，须经当地植保专家审定后方可对外输出
DEFAULT_DATA_SOURCE: str = "通用柑橘农技手册参考值（须经当地植保专家审定）"


@dataclass(frozen=True)
class PreventionAdvice:
    """防治建议数据结构（spec 6.7-5/6/7）。

    data_source 为合规字段：上层输出时须一并透出，
    禁止在上层把未标注来源的建议当作确定结论。
    """
    prevention_measures: str
    medication_advice: str
    farming_advice: str
    data_source: str = DEFAULT_DATA_SOURCE


MONTH_PEST_MAP: dict[int, list[str]] = {
    1: [NO_RISK_LABEL],
    2: [NO_RISK_LABEL],
    3: [NO_RISK_LABEL],
    4: ["canker", "greening"],
    5: ["anthracnose", "canker", "greening"],
    6: ["red_spider_mite", "anthracnose", "canker", "greening"],
    7: ["red_spider_mite", "anthracnose", "greening"],
    8: ["red_spider_mite", "anthracnose", "greening"],
    9: ["red_spider_mite", "anthracnose", "canker", "greening"],
    10: ["canker", "greening"],
    11: [NO_RISK_LABEL],
    12: [NO_RISK_LABEL],
}

PEST_ADVICE: dict[tuple[str, str], PreventionAdvice] = {
    ("red_spider_mite", "prevention"): PreventionAdvice(
        prevention_measures="保持果园通风透光，及时清除行间杂草；干旱期加强灌溉降温，减少螨虫繁殖条件。",
        medication_advice="萌芽前喷洒矿物油 150-200 倍液封杀越冬虫源；生长季用阿维菌素 1.8% 乳油 3000 倍液预防。",
        farming_advice="定期巡园查叶背，发现零星黄白小点即标记监测；保持树冠间距，避免郁闭遮阴。",
    ),
    ("red_spider_mite", "occurred"): PreventionAdvice(
        prevention_measures="已发生红蜘蛛危害，须立即用药控制虫口密度，防止蔓延至全园。",
        medication_advice="螺螨酯 240g/L 悬浮剂 4000 倍液或阿维菌素 1.8% 乳油 2000 倍液喷施叶背，7-10 天后轮换药剂复喷一次。",
        farming_advice="剪除严重受害枝叶并集中销毁；灌溉增湿降温以抑制螨虫繁殖；避免同期使用波尔多液以免诱发螨害。",
    ),
    ("anthracnose", "prevention"): PreventionAdvice(
        prevention_measures="平衡施肥增施有机肥与钾肥，增强树势；雨季前做好排水沟渠，降低果园湿度。",
        medication_advice="春梢萌发前和幼果期各喷一次代森锰锌 80% 可湿性粉剂 600 倍液作保护性防治。",
        farming_advice="冬季清园修剪病虫枝、清除落叶落果并烧毁；保持合理修剪通风透光。",
    ),
    ("anthracnose", "occurred"): PreventionAdvice(
        prevention_measures="已发生炭疽病，须立即剪除病部组织并喷药治疗，防止病菌随雨水扩散。",
        medication_advice="咪鲜胺 25% 乳油 1000 倍液或苯醚甲环唑 10% 水分散粒剂 1500 倍液喷施，间隔 10-15 天连喷 2-3 次。",
        farming_advice="剪除病枝病果并带出园外烧毁；加强排水降湿；暂停偏施氮肥以免加重病情。",
    ),
    ("canker", "prevention"): PreventionAdvice(
        prevention_measures="严格防控潜叶蛾等伤口制造者；新梢展叶期是预防关键窗口，须提前喷药保护。",
        medication_advice="新梢自剪前喷氢氧化铜 77% 可湿性粉剂 500 倍液或春雷霉素 2% 水剂 500 倍液保护。",
        farming_advice="新梢期重点防护，台风暴雨后及时补喷；农事操作工具用 75% 酒精消毒防止交叉感染。",
    ),
    ("canker", "occurred"): PreventionAdvice(
        prevention_measures="已发生溃疡病，须立即剪除病部并烧毁，全园喷药控制蔓延，检疫性病害须上报。",
        medication_advice="氢氧化铜 77% 可湿性粉剂 400 倍液加农用链霉素 72% 可溶性粉剂 3000 倍液混喷，7-10 天复喷一次。",
        farming_advice="剪除病枝病叶病果并集中烧毁，严禁随手丢弃；修剪工具每剪一株消毒一次；暂停一切可能造成伤口的农事操作。",
    ),
    # ---- greening（柑橘黄龙病）----
    # 关键事实：目前**无有效治疗药剂**。防治对象是传播媒介柑橘木虱，
    # 而非病菌本身。任何"打药治好黄龙病"的表述都是错误的，禁止输出。
    ("greening", "prevention"): PreventionAdvice(
        prevention_measures="防控传播媒介柑橘木虱为核心：统一放梢、抹除零星早梢晚梢，使新梢整齐抽发后集中打药；新植一律使用无病苗，严禁从疫区调运接穗苗木。",
        medication_advice="新梢抽发至 1-3cm 时喷吡虫啉 10% 可湿性粉剂 2000-3000 倍液或噻虫嗪 25% 水分散粒剂 3000-4000 倍液杀灭木虱；冬季清园加喷一次联苯菊酯 10% 乳油 2000-3000 倍液杀灭越冬成虫。",
        farming_advice="每次新梢期（春梢/夏梢/秋梢）各查一次木虱，见虫即打；园边设置隔离带，及时挖除并烧毁已显症病树，防止木虱带毒转移。",
    ),
    ("greening", "occurred"): PreventionAdvice(
        prevention_measures="已检出黄龙病：属检疫性病害，须立即向当地农业农村部门上报，且须先喷药杀灭树上木虱再挖除病树，严禁直接砍伐导致木虱带毒飞散。",
        medication_advice="**黄龙病无有效治疗药剂，任何药剂均不能治愈病树**。可使用的药剂仅用于杀灭传播媒介柑橘木虱：挖除前先喷吡虫啉 10% 可湿性粉剂 2000 倍液，1-2 天后整株挖除烧毁；全园同步开展木虱统防统治。",
        farming_advice="病树整株挖除（或先齐地面锯除主干、桩口涂草甘膦后覆土）并集中销毁，不得留在园边；重病园建议整园更新重建并改种无病大苗；发病株率过高时须评估全园更新，避免继续投入无效防治成本。",
    ),
}

GENERAL_ADVICE: dict[int, str] = {
    1: "冬季清园期：全面修剪病虫枝、枯枝和交叉枝，收集落叶落果集中烧毁；全园喷一次杀虫剂杀灭越冬木虱（黄龙病防控关键环节）；树干涂白防冻防虫；完成冬施基肥。",
    2: "冬末春初：继续清园收尾，春梢萌动前施催芽肥（以氮肥为主）；趁木虱尚未活动完成上年黄龙病树的挖除烧毁；检查防寒防冻措施，注意倒春寒预警。",
    3: "春梢抽发期：防寒防冻为首要任务，寒潮来临前灌水或熏烟；春梢开始萌发即进入木虱防控首轮窗口，见梢即查虫；春梢展叶后开始防治溃疡病和炭疽病；疏除过多春梢。",
    4: "春梢展叶至花前：溃疡病预防关键期，新梢展叶期喷铜制剂保护；木虱进入首个繁殖高峰，新梢 1-3cm 时打药；注意花前施肥以磷钾肥为主；防潜叶蛾。",
    5: "花期至幼果期：保花保果，谢花后喷保果剂；炭疽病和溃疡病预防喷药；夏梢萌发前抹梢控梢，减少木虱食源；注意排水防渍；疏去畸形果和过密果。",
    6: "幼果膨大期：红蜘蛛、炭疽病、溃疡病均进入高发期，加强病虫监测与防治；夏梢期木虱防控不可松懈；果实套袋防虫；注意排水和灌溉。",
    7: "高温盛夏：红蜘蛛高发期，每 5-7 天巡园一次，发现即治；早夏梢统一抹除、控梢断木虱繁殖链；注意灌溉防旱；暂停高温时段喷药，改在傍晚施药。",
    8: "持续高温期：虫害持续高发，红蜘蛛防治不可松懈；秋梢萌发前完成抹梢；注意抗旱保墒；防日灼果，可喷石灰乳或套袋遮阳。",
    9: "秋梢抽发期：溃疡病预防关键期，秋梢展叶期喷药保护；秋梢期是木虱全年最高峰，须重点打药；果实膨大后期防裂果，保持水分均衡供应；防吸果夜蛾。",
    10: "采收准备期：注意溃疡病防治，采前 15 天停止用药；此时黄龙病「红鼻果」症状最典型，巡园时重点识别并标记病株，为采后挖除做准备；检查果实成熟度，分期采收。",
    11: "采后恢复期：施采果肥恢复树势，以有机肥和磷钾肥为主；采后立即喷药杀木虱再挖除黄龙病树，并集中烧毁；采后清园，清除残枝落果；树干涂白防冻防虫。",
    12: "冬季管理期：全面清园保暖防冻，根颈培土；回暖日喷药杀灭越冬木虱成虫；完成冬剪和冬施基肥；检修排灌设施；制定来年管理计划。",
}


def get_month_pests(month: int) -> list[str]:
    """返回当月可能发生的病虫害 label 集合。

    无特定风险月份（1/2/3/11/12）返回 [NO_RISK_LABEL]，
    其中的 healthy 表示"无风险期"占位符，不是可识别类别；
    调用方须过滤 NO_RISK_LABEL 后再按检测类处理。
    month 不在 1-12 时返回空列表不抛异常（spec 6.6-5、design 接口 13）。
    """
    return list(MONTH_PEST_MAP.get(month, []))


def get_risk_labels(month: int) -> list[str]:
    """返回当月真实的检测类风险集合（已剔除 NO_RISK_LABEL 占位符）。

    无特定风险月份返回空列表。供上层直接使用，避免各处重复过滤。
    """
    return [p for p in MONTH_PEST_MAP.get(month, []) if p != NO_RISK_LABEL]


def is_quarantine(label: str) -> bool:
    """该病虫害是否为检疫性病害（检出须上报）。

    目前仅 greening（柑橘黄龙病）；上层对 true 的条目必须输出上报提示。
    """
    return label in QUARANTINE_PESTS


def is_no_risk_month(month: int) -> bool:
    """当月是否为无特定病虫害风险期（1/2/3/11/12 月）。"""
    return get_risk_labels(month) == []


def get_advice(label: str, status: str) -> PreventionAdvice:
    """按 (label, status) 返回防治建议对象。

    status 为 "prevention" 返回预防性用药方案、为 "occurred" 返回治疗性用药方案；
    (label, status) 不匹配时返回默认"无特定风险"口径建议不抛异常
    （spec 6.7-6、design 接口 13）。
    """
    return PEST_ADVICE.get(
        (label, status),
        PreventionAdvice(
            prevention_measures="当前无特定病虫害风险，保持常规果园管理即可。",
            medication_advice="无需针对性用药，按常规养护执行。",
            farming_advice="加强巡园观察，发现异常及时记录并咨询农技专家。",
        ),
    )


def get_general_advice(month: int) -> str:
    """返回当月常规养护建议文本。

    month 不在 1-12 时返回空字符串不抛异常（spec 6.7-9、design 接口 13）。
    """
    return GENERAL_ADVICE.get(month, "")


# 模块加载时数据结构完整性断言（spec 5.7.1-9、6.6-6、DFX 4.2-6）
assert set(MONTH_PEST_MAP.keys()) == set(range(1, 13)), "MONTH_PEST_MAP 须覆盖 1-12 全部月份"
assert all(len(v) > 0 for v in MONTH_PEST_MAP.values()), "MONTH_PEST_MAP 每月须非空列表"

# 兼容性校验：本文件类别口径必须与 labelmap.CLASS_NAMES 一致
try:
    import labelmap as _labelmap  # noqa: E402
except ImportError:  # 独立使用时跳过（纯标准库要求）
    _labelmap = None
if _labelmap is not None:
    _month_labels = {p for v in MONTH_PEST_MAP.values() for p in v if p != NO_RISK_LABEL}
    assert _month_labels <= set(_labelmap.CLASS_NAMES), (
        f"MONTH_PEST_MAP 含非检测类标签: {_month_labels - set(_labelmap.CLASS_NAMES)}"
    )
    assert set(_labelmap.CLASS_NAMES) <= _month_labels, (
        f"检测类未在农事历中覆盖: {set(_labelmap.CLASS_NAMES) - _month_labels}"
    )
    assert _labelmap.HEALTHY_LABEL == NO_RISK_LABEL, "healthy 标签口径与 labelmap 不一致"

_expected_advice_keys = {
    (name, status)
    for name in ("red_spider_mite", "anthracnose", "canker", "greening")
    for status in ("prevention", "occurred")
}
assert set(PEST_ADVICE.keys()) == _expected_advice_keys, (
    "PEST_ADVICE 须覆盖 4 类病虫害 × 2 种 status 共 8 组"
)
for _key, _advice in PEST_ADVICE.items():
    assert _advice.prevention_measures, f"PEST_ADVICE[{_key}].prevention_measures 须非空"
    assert _advice.medication_advice, f"PEST_ADVICE[{_key}].medication_advice 须非空"
    assert _advice.farming_advice, f"PEST_ADVICE[{_key}].farming_advice 须非空"
    assert _advice.data_source, f"PEST_ADVICE[{_key}].data_source 须非空（合规要求）"

assert set(GENERAL_ADVICE.keys()) == set(range(1, 13)), "GENERAL_ADVICE 须覆盖 1-12 全部月份"
assert all(v for v in GENERAL_ADVICE.values()), "GENERAL_ADVICE 每月建议须非空"

# 检疫性病害必须有对应建议条目，否则上报逻辑会给出空内容
assert QUARANTINE_PESTS <= {k[0] for k in PEST_ADVICE.keys()}, (
    "检疫性病害须在 PEST_ADVICE 中有防治建议"
)
