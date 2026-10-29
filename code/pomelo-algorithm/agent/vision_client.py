#!/usr/bin/env python3
"""华为云 MaaS 多模态大模型客户端（图文诊断主链路）。

赛题评估会统计 Token 消耗量，本模块是"把 Token 烧起来"的入口：
把柚叶照片 + 文本问题直接送给华为云多模态大模型，拿回结构化诊断结论。

接口依据（华为云帮助中心 2026-10）：
- OpenAI 兼容端点：https://api.modelarts-maas.com/openai/v1/chat/completions
  （中国大陆站，仅"西南-贵阳一"；中国香港站用控制台"调用说明"给出的地址）
- 鉴权：Authorization: Bearer $MAAS_API_KEY
- 图片：{"type": "image_url", "image_url": {"url": "data:image/<fmt>;base64,<b64>"}}
  支持 png / jpeg / jpg / webp / bmp / tiff，也支持公网可访问 URL
- 单次可传多张图

用法：
    export MAAS_API_KEY="你的Key"
    python agent/vision_client.py --image dataset/pomelo_yolo/images/val/xxx.jpg

    # 批量跑 50 张验证准确率（导师指定动作）
    python agent/vision_client.py --image-dir <目录> --limit 50 --report report.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:  # pragma: no cover - 环境缺依赖时给出明确指引
    sys.exit("缺少 requests：pip install requests -i https://mirrors.aliyun.com/pypi/simple/")

# ---------------------------------------------------------------- 配置

# 端点可由环境变量覆盖，便于在香港站/贵阳站之间切换
BASE_URL = os.getenv(
    "MAAS_BASE_URL", "https://api.modelarts-maas.com/openai/v1"
).rstrip("/")
CHAT_URL = f"{BASE_URL}/chat/completions"

# 多模态模型；纯文本回退模型（某些账号未开通 VL 模型时用）
DEFAULT_VL_MODEL = os.getenv("MAAS_VL_MODEL", "qwen2.5-vl-72b")
FALLBACK_TEXT_MODEL = os.getenv("MAAS_TEXT_MODEL", "deepseek-v4.1-flash")

IMAGE_EXTS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png",
              ".webp": "webp", ".bmp": "bmp", ".tif": "tiff", ".tiff": "tiff"}

# Token 用量日志（评审看的就是这个数）
USAGE_LOG = Path(__file__).parent / "token_usage.jsonl"

# 病害类别口径与 labelmap 保持一致，禁止在此另行维护
CLASS_NAMES = ("red_spider_mite", "anthracnose", "canker", "greening")
CLASS_CN = {
    "red_spider_mite": "红蜘蛛",
    "anthracnose": "炭疽病",
    "canker": "溃疡病",
    "greening": "黄龙病",
}


# ---------------------------------------------------------------- 图片编码

def encode_image(path: str | Path) -> str:
    """本地图片转 base64 字符串。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"图片不存在: {p}")
    return base64.b64encode(p.read_bytes()).decode("utf-8")


def _image_part(path_or_url: str | Path) -> dict:
    """构造一条 image_url 消息片段；本地路径转 base64，http(s) 直接透传。"""
    s = str(path_or_url)
    if s.startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": s}}

    p = Path(s)
    fmt = IMAGE_EXTS.get(p.suffix.lower())
    if fmt is None:
        raise ValueError(f"不支持的图片格式: {p.suffix}（支持 {sorted(IMAGE_EXTS)}）")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/{fmt};base64,{encode_image(p)}"},
    }


# ---------------------------------------------------------------- 核心客户端

class MaaSClient:
    """华为云 MaaS 对话客户端，带 Token 用量累计与落盘。"""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: int = 120, log_usage: bool = True) -> None:
        self.api_key = api_key or os.getenv("MAAS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "未配置 MAAS_API_KEY。\n"
                "  1) 登录华为云控制台 → MaaS → API Keys → 创建并复制\n"
                "  2) 本机执行：setx MAAS_API_KEY \"你的Key\"\n"
                "  注意：Key 只在创建时完整显示一次；模型服务、Key、调用地址必须同一区域。"
            )
        self.model = model or DEFAULT_VL_MODEL
        self.timeout = timeout
        self.log_usage = log_usage
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.call_count = 0

    # -- 单次调用 ------------------------------------------------

    def chat(self, content: list[dict], system: str | None = None,
             temperature: float = 0.0, max_tokens: int = 2048,
             model: str | None = None) -> dict:
        """发一次请求。content 为多模态片段数组（text / image_url 混排）。"""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        t0 = time.time()
        try:
            resp = requests.post(CHAT_URL, headers=headers,
                                 data=json.dumps(payload), timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"网络请求失败（检查代理/网络）: {e}") from e

        latency = round(time.time() - t0, 2)

        if resp.status_code == 401 or resp.status_code == 403:
            raise RuntimeError(
                f"鉴权失败 {resp.status_code}：{resp.text[:200]}\n"
                "检查 API Key 是否有效、模型是否已开通、Key 与调用地址是否同一区域。"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"调用失败 {resp.status_code}：{resp.text[:300]}")

        data = resp.json()
        usage = data.get("usage") or {}
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)

        self.total_prompt_tokens += pt
        self.total_completion_tokens += ct
        self.call_count += 1

        if self.log_usage:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "model": model or self.model,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "total_tokens": pt + ct,
                    "latency_s": latency,
                }, ensure_ascii=False) + "\n")

        text = ""
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"响应结构异常: {json.dumps(data, ensure_ascii=False)[:300]}") from e

        return {
            "text": text,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            "latency_s": latency,
            "model": model or self.model,
        }

    # -- 业务封装 ------------------------------------------------

    def diagnose(self, images: Iterable[str | Path], extra_text: str = "",
                 system_prompt: str | None = None) -> dict:
        """图文诊断：把图片 + 可选补充描述送模型，要求返回 JSON 结论。"""
        content: list[dict] = []
        imgs = list(images)
        if not imgs:
            raise ValueError("至少需要一张图片")
        for i, im in enumerate(imgs, 1):
            content.append({"type": "text", "text": f"图{i}："})
            content.append(_image_part(im))
        content.append({
            "type": "text",
            "text": extra_text or "请按系统提示词要求输出 JSON 诊断结论。",
        })

        result = self.chat(content, system=system_prompt, temperature=0.0)
        result["parsed"] = parse_json_relaxed(result["text"])
        return result

    def summary(self) -> str:
        total = self.total_prompt_tokens + self.total_completion_tokens
        return (f"调用 {self.call_count} 次 | 输入 {self.total_prompt_tokens} "
                f"| 输出 {self.total_completion_tokens} | 合计 {total} tokens")


# ---------------------------------------------------------------- 解析辅助

def parse_json_relaxed(text: str) -> Any:
    """从模型输出里尽力抠出 JSON：容忍 ```json 代码块与前后废话。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def validate_diagnosis(parsed: Any) -> list[str]:
    """校验诊断结论是否符合类别口径，返回问题列表（空列表 = 合格）。"""
    problems: list[str] = []
    if not isinstance(parsed, dict):
        return ["输出不是 JSON 对象"]

    label = parsed.get("label")
    if label not in CLASS_NAMES and label != "healthy":
        problems.append(f"label 非法: {label}（应为 {CLASS_NAMES} 或 healthy）")

    conf = parsed.get("confidence")
    if isinstance(conf, (int, float)) and not 0.0 <= float(conf) <= 1.0:
        problems.append(f"confidence 越界: {conf}")

    alt = parsed.get("alternatives")
    if isinstance(alt, list):
        for a in alt:
            if isinstance(a, dict) and a.get("label") not in CLASS_NAMES:
                problems.append(f"alternatives 含非法类别: {a.get('label')}")
    return problems


# ---------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="华为云 MaaS 柚叶图文诊断")
    ap.add_argument("--image", help="单张图片路径或公网 URL")
    ap.add_argument("--image-dir", help="批量：图片目录")
    ap.add_argument("--limit", type=int, default=0, help="批量时最多处理 N 张（0=全部）")
    ap.add_argument("--text", default="", help="补充文本（如'叶背也有斑'）")
    ap.add_argument("--model", default=None, help="覆盖模型名")
    ap.add_argument("--report", help="批量结果写入 JSON 报告")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from agent.vision_prompt import VISION_SYSTEM_PROMPT  # type: ignore
    except Exception:
        VISION_SYSTEM_PROMPT = None
        print("[警告] 未加载 vision_prompt.VISION_SYSTEM_PROMPT，将以裸提示调用")

    client = MaaSClient(model=args.model)

    targets: list[Path] = []
    if args.image:
        targets.append(Path(args.image))
    elif args.image_dir:
        d = Path(args.image_dir)
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in IMAGE_EXTS:
                targets.append(p)
                if args.limit and len(targets) >= args.limit:
                    break
    if not targets:
        ap.error("需要 --image 或 --image-dir")

    results = []
    for p in targets:
        print(f"\n===== {p.name} =====")
        try:
            r = client.diagnose([p], extra_text=args.text,
                                system_prompt=VISION_SYSTEM_PROMPT)
        except Exception as e:
            print(f"  [失败] {e}")
            results.append({"image": str(p), "error": str(e)})
            continue

        parsed = r["parsed"]
        problems = validate_diagnosis(parsed)
        label = (parsed or {}).get("label", "?")
        print(f"  结论: {label} ({CLASS_CN.get(label, '')})")
        print(f"  置信度: {(parsed or {}).get('confidence', '?')}")
        print(f"  Token: {r['total_tokens']}（输入 {r['prompt_tokens']} / 输出 {r['completion_tokens']}）"
              f"  耗时 {r['latency_s']}s")
        if problems:
            print(f"  [口径问题] {'; '.join(problems)}")
        if parsed is None:
            print(f"  原始输出: {r['text'][:200]}")

        results.append({
            "image": str(p),
            "parsed": parsed,
            "problems": problems,
            "tokens": r["total_tokens"],
            "latency_s": r["latency_s"],
        })

    print("\n" + "=" * 50)
    print(client.summary())

    if args.report:
        ok = sum(1 for x in results if x.get("parsed") and not x.get("problems"))
        Path(args.report).write_text(json.dumps({
            "model": client.model,
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(results),
            "structured_ok": ok,
            "structured_rate": round(ok / len(results), 3) if results else 0,
            "token_summary": client.summary(),
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入: {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
