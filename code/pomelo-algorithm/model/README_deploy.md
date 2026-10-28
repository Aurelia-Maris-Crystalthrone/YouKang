# 在线服务部署操作守则（ModelArts AI 应用）

> 对应 spec 5.4 在线病虫害识别服务；本服务是云端智能体"视觉识别"能力的数据源。

## 1. 部署包打包（自包含 model/ 目录）

目录内容（缺一不可）：
```
model/
├── config.json             # runtime 声明（python3.7 / pytorch1.8）+ 模型路径 + API 定义
├── customize_service.py    # BaseService 三段式（letterbox → 推理 → 过滤+NMS → JSON）
├── labelmap.py             # 类别映射打包副本（与项目根 labelmap.py 保持一致）
└── best.pt                 # 达标权重（mAP@0.5 ≥ 0.5，禁止交付未达标权重）
```

打包：
```bash
cd pomelo-algorithm/model
zip -r pomelo_model.zip config.json customize_service.py labelmap.py best.pt
```

## 2. 上传 OBS 并导入

```bash
obsutil cp pomelo_model.zip obs://pomelo-agent/model/
```

1. ModelArts 控制台 → 模型管理 → 导入：元模型来源选 OBS（pomelo_model.zip），
   推理引擎选 PyTorch（python3.7 + pytorch1.8）。
2. 导入成功后进入 AI 应用列表。

## 3. 部署为在线服务

1. ModelArts → 部署 → 在线服务 → 从 AI 应用导入。
2. 实例规格满足 ≥ 5 并发识别请求（spec DFX 4.1-4），单张响应 ≤ 3 秒（服务端处理）。
3. 部署成功后获取 **API 地址**（预测接口 URL）。

## 4. Token 鉴权与交付（spec 5.4.1-6/7）

1. 在线服务鉴权模式启用 **Token 鉴权**（App 认证/AK-SK 获取 Token）。
2. 交付口径：**API 地址 + Token 通过线下方式交付工程**，供智能体封装为"视觉识别"工具。
3. **Token 禁止硬编码于仓库或明文写入代码**（spec DFX 4.3-2）。

调用示例（工程侧验证）：
```bash
curl -X POST {api_base} -H "X-Auth-Token: <token>" -F "images=@leaf.jpg"
```

预期响应：
```json
{"detections": [{"label": "anthracnose", "confidence": 0.87, "bbox": [x1, y1, x2, y2]}]}
```

- label ∈ 4 类体系（red_spider_mite/anthracnose/canker/healthy），bbox 为原图像素坐标（x1<x2、y1<y2）
- 无目标时 detections 为空数组（HTTP 200，正常业务结果）
- 非法图片：`{"error_code": "INPUT_INVALID", "message": "..."}`
- 内部异常：`{"error_code": "INTERNAL_ERROR", "message": "..."}`（单次失败不影响后续请求）

## 5. 异常排查

| 现象 | 排查 |
|------|------|
| 鉴权失败（401 语义） | 工程核对 Token 有效性后重试（spec 5.4.3-1） |
| INPUT_INVALID | 确认请求为 multipart 且字段名 images、图片未损坏（spec 5.4.3-2） |
| 响应时间超 3 秒 | 检查实例规格与并发数（spec DFX 4.1） |
| 结果坐标偏差 | 按 postprocess/README.md 端云对拍流程定位预处理/解码/NMS 差异环节 |