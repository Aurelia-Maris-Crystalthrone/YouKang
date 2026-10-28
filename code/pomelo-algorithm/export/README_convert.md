# converter_lite 端侧转换守则（ONNX → MindSpore Lite .ms）

> 前置条件：`training/export_notebook.sh` 已产出达标 best.pt 对应的 `best.onnx`
>（输入 shape 必须为 `[1,3,640,640]`，batch 固定 1）。
> converter_lite 为**本地安装工具**（下载地址见行动指南第十章），区别于 Notebook 训练环境。

## 1. 转换前校验（可选确认）

YOLOv5 导出的 ONNX 输入节点名一般为 `images`，shape 为 `[1,3,640,640]`。
如需复核，可用 [netron.app](https://netron.app) 打开 `best.onnx` 确认输入节点名与 shape
（spec 5.3.1-2：netron.app 复核为可选确认手段）。

## 2. FP32 版转换（baseline / 验证阶段，指令 4.2）

```bash
converter_lite --fmk=ONNX \
  --modelFile=best.onnx \
  --outputFile=yolov5s_pomelo \
  --inputShape="images:1,3,640,640"
```

- 产出 `yolov5s_pomelo.ms`。
- **成功标志**：终端输出 `CONVERTER RESULT SUCCESS:0` 才算成功；
  非 `SUCCESS:0` 时不产出交付物，排查输入名/批次配置后重试（spec 5.3.1-6）。

## 3. 量化版转换（决赛阶段前产出，指令 4.3）

```bash
converter_lite --fmk=ONNX \
  --modelFile=best.onnx \
  --outputFile=yolov5s_pomelo_quant \
  --inputShape="images:1,3,640,640" \
  --quantType=WEIGHT_QUANT
```

- 产出 `yolov5s_pomelo_quant.ms`。

## 4. 体积校验（交付门禁）

```bash
python tools/check_model_size.py --file yolov5s_pomelo.ms          # FP32 ≤ 20MB
python tools/check_model_size.py --file yolov5s_pomelo_quant.ms    # 量化 ≤ 7MB
```

- 超限时不得交付，改用量化（WEIGHT_QUANT）或压缩方案（spec 5.3.1-5）。

## 5. 交付流转

1. 转换成功且体积达标的 `.ms` 文件先放于本项目 `export/` 目录（项目所在地副本）。
2. 再交付至鸿蒙 APP 资源目录（rawfile）；项目目录保留交付物副本（spec 5.6.1-5）。

## 6. 异常处理

| 现象 | 排查 |
|------|------|
| converter_lite 工具不可用 | 工具未安装或路径未配置，按行动指南第十章下载安装后重试（spec 5.3.3-4） |
| 转换输出非 `SUCCESS:0` | 确认 ONNX 以 `--batch 1` 导出（spec 5.3.3-1）；用 netron.app 复核输入节点名与 shape 后修正 `--inputShape` 重试 |
| 转换失败无 .ms 产出 | 不产出交付物，排查 ONNX 导出参数后重新转换（spec 5.3.3-3） |
| 模型体积超限 | FP32 超 20MB 或量化超 7MB → 检查量化参数/模型裁剪（spec 5.3.3-5） |