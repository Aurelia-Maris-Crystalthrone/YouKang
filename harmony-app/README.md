# 柚康 · 基于鸿蒙的柚子病虫害识别 APP（端云协同 Demo）

> 华为 ICT 大赛创新赛 赛题一 配套前端：鸿蒙原生 APP + 云端智能体的端云协同 Demo。

## 功能

- 拍照 / 选图识别柚子叶片病害（红蜘蛛、炭疽病、溃疡病）
- **端侧**：MindSpore Lite 加载 `yolov5s_pomelo.ms`，离线实时识别
- **云端**：调用华为云智能体 API（ModelArts Studio Agent开发），返回识别 + 防治建议 + 多轮问答
- UI 标注结果来源（端侧 / 云端），体现端云协同

## 运行步骤

1. 安装 [DevEco Studio](https://developer.huawei.com/consumer/cn/deveco-studio/)，配 HarmonyOS SDK（API 11/12，Stage 模型）。
2. 用 DevEco 打开本目录（entry 为应用模块）。
3. 把转换好的 `yolov5s_pomelo.ms` 放入 `entry/src/main/resources/rawfile/`。
4. 在 `entry/src/main/ets/common/AgentClient.ets` 填入智能体 API 域名与鉴权（勿硬编码密钥进 git）。
5. 连接鸿蒙模拟器或真机（开启 USB 调试），点击 Run。

## 模型准备（算法）

```bash
# 训练后导出 ONNX
python export.py --weights best.pt --include onnx --img 640 --batch 1
# 转 MindSpore Lite .ms
converter_lite --fmk=ONNX --modelFile=best.onnx \
  --outputFile=yolov5s_pomelo --inputShape="images:1,3,640,640"
```

## 需核实

- MindSpore Lite 在 NEXT 的导入路径与 API（`@ohos.ai.mindsporelite` vs `@kit.MindSporeLiteKit`）。
- 智能体 API 的 endpoint / 鉴权 / 请求体结构。
- 真机 NPU 加速需 `target=['nnrt']` 配置（以官方为准）。
