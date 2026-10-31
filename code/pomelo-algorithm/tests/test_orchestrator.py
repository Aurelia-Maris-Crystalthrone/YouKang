"""智能体主编排链路单元测试。

覆盖 8 个分支与零真实网络约束：
- 正常开方 / 无 DB 降级 / 健康 / 检疫性 / 低置信问诊 / 解析失败
- 类别口径非法 / 无合规药剂 / 白名单外药名 / 归一化兜底
- 追问续答 / Token 汇总 / CLI 缺 Key

全部使用 FakeClient / FakeConn / FakePrescriber，不产生任何真实网络请求。
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_load_from_db import FakeConn, _pesticide_row  # noqa: E402

from agent.orchestrator import AgentResult, PomeloAgent, _normalize_detection  # noqa: E402
from vision_client import parse_json_relaxed  # noqa: E402


class FakeClient:
    """图文诊断与文案生成的测试桩，记录调用次数与 Token。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.last_system_prompt = None

    def diagnose(self, images, extra_text="", system_prompt=None):
        """返回预设诊断文本，并用真实解析器解析。"""
        self.call_count += 1
        self.last_system_prompt = system_prompt
        text = self.responses.pop(0) if self.responses else ""
        parsed = parse_json_relaxed(text)
        prompt_tokens, completion_tokens = 10, 5
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        return {
            "text": text,
            "parsed": parsed,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_s": 0.0,
            "model": "fake-vl",
        }

    def chat(self, content, system=None, temperature=0.0, max_tokens=2048, model=None):
        """文案生成桩：返回预设文本并累计 Token。"""
        self.call_count += 1
        text = self.responses.pop(0) if self.responses else "{}"
        prompt_tokens, completion_tokens = 10, 5
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        return {
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_s": 0.0,
            "model": "fake-text",
        }

    def summary(self):
        """与 MaaSClient 同风格的汇总串。"""
        total = self.total_prompt_tokens + self.total_completion_tokens
        return (f"调用 {self.call_count} 次 | 输入 {self.total_prompt_tokens} "
                f"| 输出 {self.total_completion_tokens} | 合计 {total} tokens")


class FakePrescriber:
    """处方文案组件测试桩，可指定卡片文本以测试护栏。"""

    def __init__(self, text=None):
        self.text = text
        self.calls = 0

    def generate_prescription(self, client, diagnosis, allowed, rejected, orchard, month):
        """按放行药剂生成结构化处方与卡片文本。"""
        self.calls += 1
        name = getattr(allowed[0], "common_name", "阿维菌素") if allowed else "阿维菌素"
        text = self.text or f"推荐方案：\n 1. {name}（安全间隔期 7 天）"
        return {
            "text": text,
            "parsed": {"prescription": [{"pesticide_name": name}]},
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
            "used_fallback": False,
            "model": "fake-text",
        }

    def render_prescription_card(self, result):
        """直接返回生成阶段的卡片文本。"""
        return result.get("text", "")


def _diag(label="canker", confidence=0.9, alternatives=None, **extra):
    """构造一份诊断 JSON 文本。"""
    data = {
        "label": label,
        "confidence": confidence,
        "symptom": "叶面有褐色病斑",
        "distinguish": "病斑平塌不隆起",
        "is_quarantine": label == "greening",
        "image_quality": "good",
        "need_more_info": False,
        "follow_up_question": "",
    }
    if alternatives is not None:
        data["alternatives"] = alternatives
    data.update(extra)
    return json.dumps(data, ensure_ascii=False)


def _make_conn(pesticides, links):
    """构造带一块标准地块的内存数据库连接。"""
    return FakeConn({
        "pesticide": pesticides,
        "pest_pesticide": links,
        "orchard": [{
            "id": 1, "block_name": "测试地块", "variety": "琯溪蜜柚", "tree_age": 8,
            "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 5.0,
        }],
        "spray_record": [],
        "pesticide_conflict": [],
        "phenophase_contraindication": [],
    })


def _red_spider_conn(banned=0):
    """构造红蜘蛛候选药剂场景。"""
    return _make_conn(
        [_pesticide_row(1, "阿维菌素", banned=banned)],
        [{"id": 1, "pest_name": "red_spider_mite", "pesticide_id": 1,
          "is_registered_for_citrus": 1, "dilution_ratio": "3000 倍液"}],
    )


def _canker_conn():
    """构造溃疡病候选药剂场景。"""
    return _make_conn(
        [_pesticide_row(3, "氢氧化铜", phi=14)],
        [{"id": 3, "pest_name": "canker", "pesticide_id": 3,
          "is_registered_for_citrus": 1, "dilution_ratio": "500 倍液"}],
    )


# ---------------------------------------------------------------- 分支测试

def test_normal_prescribe_with_db():
    """正常病害 + 有 DB + 文案组件 → 正常开方，calls 为 2。"""
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    agent = PomeloAgent(client, conn=_red_spider_conn(), prescriber=FakePrescriber())
    result = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    assert result.degraded is False
    assert result.prescription is not None
    assert "阿维菌素" in result.final_text
    assert result.tokens["calls"] == 2


def test_no_db_fallback():
    """未接数据库 → 降级并给出未校验告警。"""
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert result.degraded is True
    assert any("未接数据库" in warning for warning in result.warnings)
    assert "数据来源" in result.final_text


def test_healthy_label():
    """健康结论 → 走月度养护建议，不查库、不给处方。"""
    client = FakeClient([_diag("healthy", 0.9)])
    conn = _red_spider_conn()
    agent = PomeloAgent(client, conn=conn, month=10)
    result = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    assert result.prescription is None
    assert conn.queries == []
    assert result.degraded is False
    assert "采收" in result.final_text


def test_quarantine_greening():
    """检疫性黄龙病 → 含上报/木虱/挖除，且不含任何真实药剂名。"""
    client = FakeClient([_diag("greening", 0.9)])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert "上报" in result.final_text
    assert "木虱" in result.final_text
    assert "挖除" in result.final_text
    names = ["吡虫啉", "阿维菌素", "螺螨酯", "氢氧化铜", "代森锰锌",
             "咪鲜胺", "苯醚甲环唑", "农用链霉素", "联苯菊酯", "噻虫嗪", "矿物油"]
    for name in names:
        assert name not in result.final_text


def test_low_confidence_ask(monkeypatch):
    """低置信 → 返回追问，且只调用一次诊断模型。"""
    calls = {"count": 0}
    import agent.orchestrator as orchestrator

    original = orchestrator.validate_output

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "validate_output", counting)
    client = FakeClient([_diag("canker", 0.45,
                               alternatives=[{"label": "anthracnose", "confidence": 0.40}])])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert result.question is not None
    assert result.question["question"] in result.final_text
    assert client.call_count == 1


def test_parse_failure():
    """结论非 JSON → 降级并提示重拍。"""
    client = FakeClient(["抱歉，我无法识别这张图"])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert result.degraded is True
    assert "重拍" in result.final_text
    assert result.detection is None


def test_invalid_label_warning():
    """类别口径非法 → 进入 warnings，但流程继续。"""
    client = FakeClient([_diag("melanose", 0.9)])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert any("label 非法" in warning for warning in result.warnings)
    assert result.final_text


def test_no_allowed_pesticide(monkeypatch):
    """全部候选被规则拒绝 → 固定降级文案，跳过护栏。"""
    calls = {"count": 0}
    import agent.orchestrator as orchestrator

    def counting(*args, **kwargs):
        calls["count"] += 1
        return {"is_valid": True, "detected": [], "violations": [], "suggested_text": ""}

    monkeypatch.setattr(orchestrator, "validate_output", counting)
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    agent = PomeloAgent(client, conn=_red_spider_conn(banned=1), prescriber=FakePrescriber())
    result = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    assert result.degraded is True
    assert "无合规可用药剂" in result.final_text
    assert calls["count"] == 0


def test_guardrail_blocks_unknown_name():
    """处方卡片含白名单外药名 → 被护栏替换并记告警。"""
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    prescriber = FakePrescriber(text="推荐方案：\n 1. 多菌灵（安全间隔期 7 天）")
    agent = PomeloAgent(client, conn=_red_spider_conn(), prescriber=prescriber)
    result = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    assert "请咨询当地农技人员" in result.final_text
    assert result.warnings


@pytest.mark.parametrize("alternatives,expected_len", [
    ([{"label": "anthracnose", "confidence": 0.3},
      {"label": "canker", "confidence": 0.1}], 2),
    ([{"label": "anthracnose", "confidence": 0.3}], 2),
    (None, 1),
])
def test_normalize_detection(alternatives, expected_len):
    """归一化兜底：alternatives 两条/一条/缺省分别得到 top2 长度 2/2/1。"""
    diagnosis = {
        "label": "red_spider_mite",
        "confidence": 0.9,
        "alternatives": alternatives,
    }
    detection = _normalize_detection(diagnosis)
    assert len(detection["top2"]) == expected_len
    assert detection["confidence"] == 0.9


def test_answer_followup_escalates():
    """追问后置信度提升 → 进入开方分支，Token 跨轮累加。"""
    client = FakeClient([_diag("canker", 0.55,
                               alternatives=[{"label": "anthracnose", "confidence": 0.45}])])
    agent = PomeloAgent(client, conn=_canker_conn(), prescriber=FakePrescriber())
    first = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    assert first.question is not None
    assert first.tokens["calls"] == 1

    second = agent.answer_followup(first, "raised")
    assert second.question is None
    assert second.tokens["calls"] == 2
    assert second.prescription is not None


def test_answer_followup_still_low():
    """追问后仍低于地板 → 返回新追问，不查库、不新增调用。"""
    client = FakeClient([_diag("canker", 0.55,
                               alternatives=[{"label": "anthracnose", "confidence": 0.45}])])
    conn = _canker_conn()
    agent = PomeloAgent(client, conn=conn, prescriber=FakePrescriber())
    first = agent.diagnose(["leaf.jpg"], orchard_name="测试地块")
    second = agent.answer_followup(first, "不存在的答案")
    assert second.question is not None
    assert conn.queries == []
    assert second.tokens["calls"] == 1


def test_token_summary_format():
    """Token 汇总格式含调用次数与 tokens。"""
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    agent = PomeloAgent(client, conn=None)
    agent.diagnose(["leaf.jpg"])
    summary = agent.token_summary()
    assert "tokens" in summary
    assert "调用 1 次" in summary


def test_db_without_orchard_name():
    """有 DB 但缺地块名 → 降级，不查处方引擎。"""
    client = FakeClient([_diag("canker", 0.9)])
    conn = _canker_conn()
    agent = PomeloAgent(client, conn=conn, prescriber=FakePrescriber())
    result = agent.diagnose(["leaf.jpg"], orchard_name=None)
    assert result.degraded is True
    assert result.warnings
    assert conn.queries == []


def test_cli_missing_key(monkeypatch, capsys):
    """缺 MAAS_API_KEY → 返回 1，打印友好指引且无堆栈。"""
    monkeypatch.setenv("MAAS_API_KEY", "")
    from agent.orchestrator import main

    code = main(["--image", "x.jpg"])
    output = capsys.readouterr().out
    assert code == 1
    assert "MAAS_API_KEY" in output
    assert "Traceback" not in output


def test_no_real_network(monkeypatch):
    """全流程零真实网络请求。"""
    def boom(*args, **kwargs):
        raise AssertionError("不应发起真实网络请求")

    monkeypatch.setattr("requests.post", boom)
    client = FakeClient([_diag("red_spider_mite", 0.9)])
    agent = PomeloAgent(client, conn=None)
    result = agent.diagnose(["leaf.jpg"])
    assert result.final_text
    assert client.call_count == 1