#!/usr/bin/env python3
"""一键离线演示脚本（不联网）。

默认用内置离线桩（_FakeClient + _FakeConn）跑通 5 个场景，展示完整主链路：
红蜘蛛 / 炭疽病 / 溃疡病 / 黄龙病 / 健康。

用法：
    python agent/demo_offline.py
    python agent/demo_offline.py --with-api      # 有 MAAS_API_KEY 时走真实链路

注意：离线模式下 Token 为模拟值；本脚本不写任何落盘产物。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parent
_ROOT = _AGENT_DIR.parent
for _path in (str(_ROOT), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from orchestrator import PomeloAgent  # noqa: E402
from vision_client import MaaSClient, parse_json_relaxed  # noqa: E402
from vision_prompt import CLASS_CN  # noqa: E402

BANNER = "【离线演示】未调用真实 API，Token 为模拟值；配置 MAAS_API_KEY 后自动切到真实链路"


class _FakeClient:
    """离线诊断桩：字段与 tests 中的 FakeClient 语义等价。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def diagnose(self, images, extra_text="", system_prompt=None):
        """返回预设诊断文本，并用真实解析器解析。"""
        self.call_count += 1
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
        """预留文案生成接口。"""
        self.call_count += 1
        text = self.responses.pop(0) if self.responses else "{}"
        return {
            "text": text,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "latency_s": 0.0,
            "model": "fake-text",
        }

    def summary(self):
        """与 MaaSClient 同风格的汇总串。"""
        total = self.total_prompt_tokens + self.total_completion_tokens
        return (f"调用 {self.call_count} 次 | 输入 {self.total_prompt_tokens} "
                f"| 输出 {self.total_completion_tokens} | 合计 {total} tokens")


def _truthy(value) -> bool:
    """把内存数据里的 1/True/"1" 归一为真。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


class _FakeConn:
    """离线数据库桩：按 SQL 文本路由，语义与 tests 中的 FakeConn 等价（跳过列校验）。"""

    def __init__(self, tables=None):
        self._tables = tables or {}
        self.queries = []

    def query(self, sql, params=None):
        """按 SQL 文本路由到内存表。"""
        self.queries.append((sql, params))
        params = params or ()
        if re.search(r"FROM\s+pesticide\s+p\s+JOIN\s+pest_pesticide\s+pp", sql):
            return self._candidates(sql, params)
        if re.search(r"FROM\s+spray_record\s+sr", sql):
            return self._spray_history(params)
        if re.search(r"FROM\s+orchard\s+o\b", sql):
            return self._orchard(params)
        if re.search(r"FROM\s+pesticide_conflict\s+pc", sql):
            return [dict(row) for row in self._tables.get("pesticide_conflict", [])]
        if re.search(r"FROM\s+phenophase_contraindication\s+pct", sql):
            return [dict(row) for row in self._tables.get("phenophase_contraindication", [])]
        raise AssertionError(f"未识别的 SQL: {sql}")

    def _candidates(self, sql, params):
        pest_name = params[0]
        citrus_only = "is_registered_for_citrus = 1" in sql
        pesticides = {row["id"]: row for row in self._tables.get("pesticide", [])}
        result = []
        for link in self._tables.get("pest_pesticide", []):
            if link.get("pest_name") != pest_name:
                continue
            if citrus_only and not _truthy(link.get("is_registered_for_citrus")):
                continue
            row = pesticides.get(link.get("pesticide_id"))
            if row is not None:
                result.append(dict(row))
        result.sort(key=lambda item: item.get("id"))
        return result

    def _spray_history(self, params):
        orchard_id, limit = params[0], params[1]
        pesticides = {row["id"]: row for row in self._tables.get("pesticide", [])}
        records = [dict(row) for row in self._tables.get("spray_record", [])
                   if row.get("orchard_id") == orchard_id]
        records.sort(key=lambda item: item.get("spray_date"), reverse=True)
        records = records[: int(limit)]
        for record in records:
            pesticide = pesticides.get(record.get("pesticide_id"), {})
            record["pesticide_name"] = pesticide.get("common_name", "")
            record["frac_irac_code"] = pesticide.get("frac_irac_code")
        return records

    def _orchard(self, params):
        block_name = params[0]
        for row in self._tables.get("orchard", []):
            if row.get("block_name") == block_name:
                return [dict(row)]
        return []


def _pesticide_row(pid, name, banned=0, phi=7, frac="6"):
    """构造一行 pesticide 内存数据。"""
    return {
        "id": pid,
        "common_name": name,
        "active_ingredient": name,
        "formulation": "乳油",
        "content": "1.8%",
        "frac_irac_code": frac,
        "phi_days": phi,
        "max_times_per_season": 2,
        "toxicity_level": "低毒",
        "is_banned": banned,
        "registered_crops": '["柑橘","柚子"]',
    }


def _make_conn(pesticides, links):
    """构造带一块标准地块的内存连接。"""
    return _FakeConn({
        "pesticide": pesticides,
        "pest_pesticide": links,
        "orchard": [{
            "id": 1, "block_name": "演示地块", "variety": "琯溪蜜柚", "tree_age": 8,
            "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 5.0,
        }],
        "spray_record": [],
        "pesticide_conflict": [],
        "phenophase_contraindication": [],
    })


def _diag(label, confidence=0.9, alternatives=None):
    """构造一份诊断 JSON 文本。"""
    symptoms = {
        "healthy": "叶色均匀正常，未见病斑或虫体",
        "red_spider_mite": "叶面有密集黄白小点",
        "anthracnose": "病斑平塌、有轮纹小黑点",
        "canker": "病斑隆起、呈火山口状开裂",
        "greening": "新梢叶片斑驳黄化",
    }
    distingishes = {
        "canker": "病斑隆起，区别于炭疽病的平塌",
        "anthracnose": "病斑平塌，区别于溃疡病的隆起",
        "greening": "斑驳黄化不对称，区别于缺素",
    }
    data = {
        "label": label,
        "confidence": confidence,
        "symptom": symptoms.get(label, "结合叶面与叶背综合判断"),
        "distinguish": distingishes.get(label, "结合叶背与病斑形态综合判断"),
        "is_quarantine": label == "greening",
        "image_quality": "good",
        "need_more_info": False,
        "follow_up_question": "",
    }
    if alternatives is not None:
        data["alternatives"] = alternatives
    return json.dumps(data, ensure_ascii=False)


SCENARIOS = [
    {
        "key": "red_spider_mite",
        "name": "红蜘蛛",
        "diagnosis": _diag("red_spider_mite"),
        "conn": _make_conn(
            [_pesticide_row(1, "阿维菌素")],
            [{"id": 1, "pest_name": "red_spider_mite", "pesticide_id": 1,
              "is_registered_for_citrus": 1, "dilution_ratio": "3000 倍液"}],
        ),
        "orchard": "演示地块",
        "extra": "叶背也有细小虫体",
    },
    {
        "key": "anthracnose",
        "name": "炭疽病",
        "diagnosis": _diag("anthracnose"),
        "conn": _make_conn(
            [_pesticide_row(2, "螺螨酯", phi=14)],
            [{"id": 2, "pest_name": "anthracnose", "pesticide_id": 2,
              "is_registered_for_citrus": 1, "dilution_ratio": "4000 倍液"}],
        ),
        "orchard": "演示地块",
        "extra": "病斑有轮纹小黑点",
    },
    {
        "key": "canker",
        "name": "溃疡病",
        "diagnosis": _diag("canker"),
        "conn": _make_conn(
            [_pesticide_row(3, "氢氧化铜", phi=14)],
            [{"id": 3, "pest_name": "canker", "pesticide_id": 3,
              "is_registered_for_citrus": 1, "dilution_ratio": "500 倍液"}],
        ),
        "orchard": "演示地块",
        "extra": "病斑隆起像火山口",
    },
    {
        "key": "greening",
        "name": "黄龙病",
        "diagnosis": _diag("greening"),
        "conn": None,
        "orchard": None,
        "extra": "新梢斑驳黄化",
    },
    {
        "key": "healthy",
        "name": "健康",
        "diagnosis": _diag("healthy"),
        "conn": None,
        "orchard": None,
        "extra": "",
    },
]


def _render_scene(index, scene, result, month):
    """打印单个场景的完整对话与处方卡片。"""
    print("")
    print("=" * 72)
    print(f"场景 {index}/{len(SCENARIOS)}：{scene['name']}")
    print("=" * 72)
    print(f"[用户] 图片：leaf_demo.jpg  补充描述：{scene['extra'] or '（无）'}")
    print(f"[诊断] {result.label} {CLASS_CN.get(result.label, '')}（置信度 {result.confidence:.2f}）")
    print(f"[症状] {result.symptom or '—'}")
    print(f"[区分] {result.distinguish or '—'}")
    print("")
    print("[处方卡片]")
    print(result.final_text)
    print("")
    print("[链路步骤]")
    for step in result.steps:
        print(f"  - {step}")
    print(f"[降级] {'是' if result.degraded else '否'}")
    print(f"[Token] 输入 {result.tokens['prompt']} | 输出 {result.tokens['completion']} "
          f"| 合计 {result.tokens['total']} | 调用 {result.tokens['calls']} 次")
    if result.warnings:
        print("[告警]")
        for warning in result.warnings:
            print(f"  - {warning}")


def main(argv: list[str] | None = None) -> int:
    """离线演示入口。"""
    parser = argparse.ArgumentParser(description="柚子病虫害智能体离线演示")
    parser.add_argument("--with-api", action="store_true",
                        help="检测到 MAAS_API_KEY 时改用真实 MaaSClient")
    parser.add_argument("--month", type=int, default=10, help="演示月份（默认 10）")
    args = parser.parse_args(argv)

    print("=" * 72)
    print(BANNER)
    print("=" * 72)

    use_api = bool(args.with_api and os.getenv("MAAS_API_KEY"))
    if args.with_api and not use_api:
        print("[提示] 未检测到 MAAS_API_KEY，--with-api 回退为离线桩。")

    totals = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
    rows = []
    for index, scene in enumerate(SCENARIOS, 1):
        if use_api:
            try:
                client = MaaSClient()
                agent = PomeloAgent(client, conn=scene["conn"], month=args.month)
                result = agent.diagnose(["leaf_demo.jpg"], extra_text=scene["extra"],
                                        orchard_name=scene["orchard"])
            except Exception as exc:  # 真实链路失败不影响演示继续
                print("")
                print(f"场景 {index}/{len(SCENARIOS)}：{scene['name']} 真实调用失败：{exc}")
                continue
        else:
            client = _FakeClient([scene["diagnosis"]])
            agent = PomeloAgent(client, conn=scene["conn"], month=args.month)
            result = agent.diagnose(["leaf_demo.jpg"], extra_text=scene["extra"],
                                    orchard_name=scene["orchard"])

        _render_scene(index, scene, result, args.month)

        for key in ("prompt", "completion", "total", "calls"):
            totals[key] += result.tokens[key]
        allowed = result.prescription.get("allowed") if isinstance(result.prescription, dict) else None
        names = "、".join(item.common_name for item in allowed) if allowed else "—"
        rows.append((scene["name"], result.label, "是" if result.degraded else "否",
                     result.tokens["total"], names))

    print("")
    print("=" * 72)
    print("模拟 Token 汇总表")
    print("=" * 72)
    print(f"{'病害':<8} | {'结论':<16} | {'是否降级':<8} | {'Token 数':<10} | 处方药名")
    print("-" * 72)
    for name, label, degraded, tokens, names in rows:
        print(f"{name:<8} | {label:<16} | {degraded:<8} | {tokens:<10} | {names}")
    print("-" * 72)
    print(f"总计：调用 {totals['calls']} 次 | 输入 {totals['prompt']} "
          f"| 输出 {totals['completion']} | 合计 {totals['total']} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())