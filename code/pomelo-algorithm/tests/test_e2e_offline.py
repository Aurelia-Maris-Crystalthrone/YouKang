"""全离线端到端冒烟测试。

覆盖 4 种病害 + healthy 各一例，验证"诊断 → 判据 → 处方规则引擎 → 本地直出卡片 → 护栏"
整条链路在无 API Key、无真实数据库时仍能产出合规结论。

零网络：文件级 autouse fixture 令 requests.post 抛异常，任何真实网络请求都会让测试失败。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_load_from_db import FakeConn, _pesticide_row  # noqa: E402
from test_orchestrator import (  # noqa: E402
    FakeClient,
    _canker_conn,
    _diag,
    _make_conn,
    _red_spider_conn,
)

from agent.orchestrator import PomeloAgent  # noqa: E402
from prescription.guardrail import validate_output  # noqa: E402

BLACKLIST = ["吡虫啉", "阿维菌素", "螺螨酯", "氢氧化铜", "代森锰锌",
             "咪鲜胺", "苯醚甲环唑", "农用链霉素", "联苯菊酯", "噻虫嗪", "矿物油"]


def _anthracnose_conn():
    """构造炭疽病候选药剂（螺螨酯）的内存连接。"""
    return _make_conn(
        [_pesticide_row(2, "螺螨酯", phi=14)],
        [{"id": 2, "pest_name": "anthracnose", "pesticide_id": 2,
          "is_registered_for_citrus": 1, "dilution_ratio": "4000 倍液"}],
    )


SCENARIOS = [
    {
        "key": "red_spider_mite",
        "name": "红蜘蛛",
        "diagnosis": _diag("red_spider_mite", 0.9),
        "conn": _red_spider_conn(),
        "orchard": "测试地块",
        "expected_name": "阿维菌素",
        "prescribable": True,
    },
    {
        "key": "anthracnose",
        "name": "炭疽病",
        "diagnosis": _diag("anthracnose", 0.9),
        "conn": _anthracnose_conn(),
        "orchard": "测试地块",
        "expected_name": "螺螨酯",
        "prescribable": True,
    },
    {
        "key": "canker",
        "name": "溃疡病",
        "diagnosis": _diag("canker", 0.9),
        "conn": _canker_conn(),
        "orchard": "测试地块",
        "expected_name": "氢氧化铜",
        "prescribable": True,
    },
    {
        "key": "greening",
        "name": "黄龙病",
        "diagnosis": _diag("greening", 0.9),
        "conn": None,
        "orchard": None,
        "expected_name": None,
        "prescribable": False,
    },
    {
        "key": "healthy",
        "name": "健康",
        "diagnosis": _diag("healthy", 0.9),
        "conn": None,
        "orchard": None,
        "expected_name": None,
        "prescribable": False,
    },
]


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """全文件禁用真实网络：任何 requests.post 调用都会失败。"""
    def boom(*args, **kwargs):
        raise AssertionError("不应发起真实网络请求")

    monkeypatch.setattr("requests.post", boom)


def _run_scene(scene):
    """用离线桩跑一个场景并返回 AgentResult。"""
    client = FakeClient([scene["diagnosis"]])
    agent = PomeloAgent(client, conn=scene["conn"], month=10)
    return agent.diagnose(["leaf.jpg"], orchard_name=scene["orchard"])


@pytest.mark.parametrize("scene", SCENARIOS, ids=[s["key"] for s in SCENARIOS])
def test_e2e_scenario(scene):
    """端到端冒烟：5 个场景均产出合规结论。"""
    result = _run_scene(scene)
    assert isinstance(result.final_text, str)
    assert result.final_text.strip()

    if scene["prescribable"]:
        assert result.degraded is True
        whitelist = [item.common_name for item in result.prescription["allowed"]]
        assert whitelist
        assert scene["expected_name"] in whitelist
        assert scene["expected_name"] in result.final_text
        check = validate_output(result.final_text, whitelist)
        assert check["is_valid"] is True
        assert check["violations"] == []
    elif scene["key"] == "greening":
        assert "上报" in result.final_text
        assert "木虱" in result.final_text
        assert "挖除" in result.final_text
        for name in BLACKLIST:
            assert name not in result.final_text
        violations = set(validate_output(result.final_text, [])["violations"])
        assert violations & set(BLACKLIST) == set()
    else:
        assert "未检出目标病害" in result.final_text
        for name in BLACKLIST:
            assert name not in result.final_text
        violations = set(validate_output(result.final_text, [])["violations"])
        assert violations & set(BLACKLIST) == set()


def test_e2e_summary_table(capsys):
    """打印中文汇总表并校验表头与 5 个场景行。"""
    rows = []
    for scene in SCENARIOS:
        result = _run_scene(scene)
        allowed = result.prescription.get("allowed") if isinstance(result.prescription, dict) else None
        names = "、".join(item.common_name for item in allowed) if allowed else "—"
        rows.append((scene["name"], result.label, "是" if result.degraded else "否",
                     result.tokens["total"], names))

    print("\n离线端到端冒烟汇总")
    print(f"{'病害':<8} | {'结论':<16} | {'是否降级':<8} | {'Token 数':<10} | 处方药名")
    print("-" * 72)
    for name, label, degraded, tokens, names in rows:
        print(f"{name:<8} | {label:<16} | {degraded:<8} | {tokens:<10} | {names}")

    output = capsys.readouterr().out
    for header in ("病害", "结论", "是否降级", "Token 数", "处方药名"):
        assert header in output
    for scene in SCENARIOS:
        assert scene["name"] in output