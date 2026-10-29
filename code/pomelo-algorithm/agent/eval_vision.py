#!/usr/bin/env python3
"""多模态大模型诊断准确率评测（导师指定动作：先用 50 张图验证准确率）。

从 `dataset/pomelo_yolo` 的 val 集按类别均衡抽样，逐张调华为云 MaaS 多模态 API，
与标注真值比对，产出：总准确率 / 分类别准确率 / 混淆矩阵 / 拒答率 / 结构化输出率 /
Token 消耗总量。这五项就是答辩时"AI 到底准不准、烧了多少 Token"的直接证据。

真值口径：
- labels 非空 → 取文件中出现次数最多的 class id 映射为类别名
- labels 为空文件 → 负样本，真值为 healthy（模型输出任一病害类 = 误报）

用法：
    export MAAS_API_KEY="..."
    python agent/eval_vision.py --per-class 10                 # 4 类 × 10 = 40 张
    python agent/eval_vision.py --per-class 13 --negatives 8   # 约 60 张
    python agent/eval_vision.py --total 50 --report eval.json  # 导师要求的 50 张
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.vision_client import (  # noqa: E402
    CLASS_NAMES, CLASS_CN, IMAGE_EXTS, MaaSClient,
    parse_json_relaxed, validate_diagnosis,
)
from agent.vision_prompt import VISION_SYSTEM_PROMPT  # noqa: E402

DATASET = Path("E:/柚子病虫害AI识别/dataset/pomelo_yolo")
NEGATIVE_LABEL = "healthy"


# ---------------------------------------------------------------- 真值读取

def read_truth(label_path: Path) -> str:
    """从 YOLO 标注文件读出真值类别；空文件视为负样本（healthy）。"""
    if not label_path.is_file() or label_path.stat().st_size == 0:
        return NEGATIVE_LABEL
    ids: list[int] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.append(int(line.split()[0]))
        except (ValueError, IndexError):
            continue
    if not ids:
        return NEGATIVE_LABEL
    top = Counter(ids).most_common(1)[0][0]
    return CLASS_NAMES[top] if 0 <= top < len(CLASS_NAMES) else NEGATIVE_LABEL


def sample_val_set(per_class: int, negatives: int, total: int,
                   seed: int = 42) -> tuple[list[tuple[Path, str]], dict]:
    """按类别均衡抽样 val 集。返回 [(图片路径, 真值), ...] 与抽样统计。"""
    import random
    rng = random.Random(seed)

    images_dir = DATASET / "images" / "val"
    labels_dir = DATASET / "labels" / "val"
    if not images_dir.is_dir():
        raise SystemExit(f"找不到验证集: {images_dir}\n请先运行 build_dataset.py 构建数据集")

    by_truth: dict[str, list[Path]] = defaultdict(list)
    for img in sorted(images_dir.iterdir()):
        if img.suffix.lower() not in IMAGE_EXTS:
            continue
        truth = read_truth(labels_dir / f"{img.stem}.txt")
        by_truth[truth].append(img)

    picked: list[tuple[Path, str]] = []
    quota = {}
    if total:
        # 总数模式：目标病害均分，负样本占 1/5
        n_cls = len(CLASS_NAMES)
        neg_n = max(1, total // 5)
        per = max(1, (total - neg_n) // n_cls)
        quota = {c: per for c in CLASS_NAMES}
        quota[NEGATIVE_LABEL] = neg_n
    else:
        quota = {c: per_class for c in CLASS_NAMES}
        quota[NEGATIVE_LABEL] = negatives

    for truth, n in quota.items():
        pool = by_truth.get(truth, [])
        rng.shuffle(pool)
        for img in pool[:n]:
            picked.append((img, truth))

    stats = {k: len(v) for k, v in by_truth.items()}
    return picked, stats


# ---------------------------------------------------------------- 评测

def evaluate(picked: list[tuple[Path, str]], model: str | None = None,
             verbose: bool = True) -> dict:
    client = MaaSClient(model=model)

    rows: list[dict] = []
    conf_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_class_total: Counter = Counter()
    per_class_correct: Counter = Counter()

    for i, (img, truth) in enumerate(picked, 1):
        if verbose:
            print(f"[{i}/{len(picked)}] {img.name[:46]:<46} 真值={CLASS_CN.get(truth, truth)}",
                  end=" ", flush=True)
        try:
            r = client.diagnose([img], system_prompt=VISION_SYSTEM_PROMPT)
        except Exception as e:
            if verbose:
                print(f"[失败] {str(e)[:40]}")
            rows.append({"image": img.name, "truth": truth, "error": str(e)})
            per_class_total[truth] += 1
            continue

        parsed = r["parsed"]
        problems = validate_diagnosis(parsed)
        pred = (parsed or {}).get("label") if isinstance(parsed, dict) else None
        conf = (parsed or {}).get("confidence") if isinstance(parsed, dict) else None
        refused = bool((parsed or {}).get("need_more_info")) or (
            isinstance(conf, (int, float)) and conf < 0.5)

        if pred:
            conf_matrix[truth][pred] += 1
        per_class_total[truth] += 1
        if pred == truth:
            per_class_correct[truth] += 1
            if verbose:
                print(f"✓ {CLASS_CN.get(pred, pred)}", end="")
        else:
            if verbose:
                print(f"✗ 预测={CLASS_CN.get(pred, pred) or pred}", end="")

        if refused and verbose:
            print(" (拒答)", end="")
        if verbose:
            print(f" | {r['total_tokens']} tok", flush=True)

        rows.append({
            "image": img.name,
            "truth": truth,
            "pred": pred,
            "confidence": conf,
            "refused": refused,
            "structured": parsed is not None and not problems,
            "problems": problems,
            "tokens": r["total_tokens"],
            "latency_s": r["latency_s"],
        })

    n = len(rows)
    ok = sum(1 for x in rows if x.get("pred") == x.get("truth"))
    structured = sum(1 for x in rows if x.get("structured"))
    refused = sum(1 for x in rows if x.get("refused"))
    answered = [x for x in rows if not x.get("refused") and x.get("pred")]

    return {
        "model": client.model,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n": n,
        "accuracy": round(ok / n, 3) if n else 0,
        # 拒答后仍答对的比例——衡量"诚实的准确"，比裸准确率更能说明可用性
        "accuracy_on_answered": round(
            sum(1 for x in answered if x.get("pred") == x.get("truth")) / len(answered), 3
        ) if answered else 0,
        "structured_rate": round(structured / n, 3) if n else 0,
        "refusal_rate": round(refused / n, 3) if n else 0,
        "per_class": {
            c: {
                "total": per_class_total[c],
                "correct": per_class_correct[c],
                "accuracy": round(per_class_correct[c] / per_class_total[c], 3)
                if per_class_total[c] else 0,
            }
            for c in sorted(per_class_total)
        },
        "confusion_matrix": {t: dict(p) for t, p in conf_matrix.items()},
        "token_usage": client.summary(),
        "total_tokens": client.total_prompt_tokens + client.total_completion_tokens,
        "rows": rows,
    }


def render_report(res: dict) -> str:
    lines = [
        "=" * 62,
        "多模态大模型诊断评测报告",
        "=" * 62,
        f"模型        : {res['model']}",
        f"样本数      : {res['n']}",
        f"总准确率    : {res['accuracy']:.1%}",
        f"作答样本准确率: {res['accuracy_on_answered']:.1%}（排除拒答）",
        f"结构化输出率: {res['structured_rate']:.1%}",
        f"拒答率      : {res['refusal_rate']:.1%}",
        f"Token 消耗  : {res['token_usage']}",
        "",
        "分类别表现：",
        f"  {'类别':<20}{'样本':>6}{'正确':>6}{'准确率':>9}",
    ]
    for c, v in res["per_class"].items():
        lines.append(f"  {CLASS_CN.get(c, c):<20}{v['total']:>6}{v['correct']:>6}{v['accuracy']:>8.1%}")

    if res["confusion_matrix"]:
        lines += ["", "混淆矩阵（行=真值，列=预测）："]
        preds = sorted({p for row in res["confusion_matrix"].values() for p in row})
        lines.append("  " + "真值\\预测".ljust(14) + "".join(f"{CLASS_CN.get(p, p)[:6]:>8}" for p in preds))
        for t, row in res["confusion_matrix"].items():
            lines.append("  " + f"{CLASS_CN.get(t, t)[:12]:<14}"
                         + "".join(f"{row.get(p, 0):>8}" for p in preds))
    lines.append("=" * 62)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="多模态大模型诊断准确率评测")
    ap.add_argument("--per-class", type=int, default=10, help="每个目标病害类抽样张数")
    ap.add_argument("--negatives", type=int, default=6, help="负样本（健康/易混淆）抽样张数")
    ap.add_argument("--total", type=int, default=0, help="指定总张数（覆盖前两项，如 50）")
    ap.add_argument("--model", default=None, help="覆盖模型名")
    ap.add_argument("--report", help="结果写入 JSON 文件")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    picked, pool_stats = sample_val_set(args.per_class, args.negatives, args.total)
    print(f"验证集各类可用量: {pool_stats}")
    print(f"本次抽样 {len(picked)} 张\n")

    res = evaluate(picked, model=args.model, verbose=not args.quiet)
    print("\n" + render_report(res))

    if args.report:
        Path(args.report).write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"\n完整结果: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
