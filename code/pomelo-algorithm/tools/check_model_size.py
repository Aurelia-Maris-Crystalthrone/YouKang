"""模型体积门禁：校验端侧 .ms 文件体积（FP32 ≤ 20MB、量化版 ≤ 7MB，spec 4.1-3）。

用法：
    python check_model_size.py --file yolov5s_pomelo_quant.ms
    python check_model_size.py --file yolov5s_pomelo.ms --limit-mb 20

退出码：0 = 通过；非 0 = 超限或异常（可被守则流程串联）。
"""
import argparse
import os
import sys

FP32_LIMIT_MB: float = 20.0
QUANT_LIMIT_MB: float = 7.0


def limit_for(filename: str, explicit_mb: float | None) -> tuple[float | None, str]:
    stem = os.path.basename(filename).lower()
    if explicit_mb is not None:
        return explicit_mb, "explicit"
    if "quant" in stem:
        return QUANT_LIMIT_MB, "quant"
    if stem.endswith(".ms") or "pomelo" in stem:
        return FP32_LIMIT_MB, "fp32"
    return None, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="端侧 .ms 模型体积校验门禁")
    parser.add_argument("--file", required=True, help="模型文件路径")
    parser.add_argument("--limit-mb", type=float, default=None, help="显式指定体积上限（MB）")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"[体积门禁] 报错：文件不存在: {args.file}")
        return 2

    limit, kind = limit_for(args.file, args.limit_mb)
    if limit is None:
        print("[体积门禁] 报错：无法判定模型类型（文件名需含 quant 或为 .ms 文件），"
              "或请显式指定 --limit-mb")
        return 2

    size_mb = os.path.getsize(args.file) / (1024 * 1024)
    if size_mb <= limit:
        print(f"[体积门禁] 通过：{args.file} = {size_mb:.2f}MB ≤ {limit:g}MB（上限类别: {kind}）")
        return 0
    print(f"[体积门禁] 超限：{args.file} = {size_mb:.2f}MB > {limit:g}MB（上限类别: {kind}），"
          f"不得交付，需改用量化（WEIGHT_QUANT）或压缩方案")
    return 3


if __name__ == "__main__":
    sys.exit(main())