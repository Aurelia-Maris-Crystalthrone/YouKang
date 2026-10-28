# 打药效果追踪模块对接说明

## 模块定位

本模块把"一次性识别"变成"持续管理服务"。全场几乎没有项目做这个——这是核心差异化。

**核心价值**：
- 不是"今天有病没病"，而是"病在加重还是好转"
- 不是"开一次药"，而是"药有没有效，要不要换"
- 把零散的识别结果串成"病情曲线"，让柚农看到趋势

## 数据库表结构

### 核心表

| 表名 | 用途 |
|------|------|
| `observation` | 观测记录（每次拍摄的图片及检测结果） |
| `disease_trend` | 病情趋势（每次比较的结果） |
| `v_disease_curve` | 病情曲线视图（用于鸿蒙 APP 渲染） |

### observation 表关键字段

```sql
-- 检测结果 JSON 结构
{
  "detections": [
    {
      "label": "canker",
      "confidence": 0.85,
      "bbox": [100, 100, 150, 150],
      "top2": [
        {"label": "canker", "score": 0.85},
        {"label": "anthracnose", "score": 0.42}
      ]
    }
  ],
  "is_healthy": false
}
```

## 鸿蒙 APP 数据对接

### 数据结构约定（ArkTS）

```typescript
// 观测记录
interface Observation {
  id: number;
  orchard_id: number;
  captured_at: string;  // ISO 8601 格式，如 "2026-10-28T14:30:00Z"
  image_obs_path: string;  // OBS 路径
  detections: Detection[];
  is_healthy: boolean;
}

// 单个检测结果
interface Detection {
  label: string;  // "canker" | "anthracnose" | "red_spider_mite" | "greening"
  confidence: number;
  bbox: [number, number, number, number];  // [x1, y1, x2, y2]
  top2: Top2Item[];
}

interface Top2Item {
  label: string;
  score: number;
}

// 病情趋势
interface DiseaseTrend {
  conclusion: "SPREADING" | "STABLE" | "RECOVERING";
  prev_lesion_count: number;
  curr_lesion_count: number;
  lesion_count_change: number;
  prev_total_area: number;
  curr_total_area: number;
  total_area_change_rate: number;
  new_lesions: Array<{ x: number; y: number }>;
  disappeared_lesions: Array<{ x: number; y: number }>;
  summary: string;
}

// 病情曲线数据点（用于图表渲染）
interface CurveDataPoint {
  date: string;  // 如 "10/20"
  lesion_count: number;
  total_area: number;
  conclusion: "SPREADING" | "STABLE" | "RECOVERING";
  recommendation: string;
}

// 完整病情曲线
interface DiseaseCurve {
  orchard_id: number;
  orchard_name: string;
  disease_label: string;
  data_points: CurveDataPoint[];
}
```

### API 接口

#### 获取病情曲线

```typescript
// GET /api/disease_curve?orchard_id=1&disease_label=canker
// 返回：
{
  "orchard_id": 1,
  "orchard_name": "A区1号",
  "disease_label": "canker",
  "data_points": [
    {
      "date": "10/20",
      "lesion_count": 3,
      "total_area": 1250.5,
      "conclusion": "STABLE",
      "recommendation": "维持现有防治方案，7天后再次观测确认趋势。"
    },
    {
      "date": "10/28",
      "lesion_count": 5,
      "total_area": 1890.2,
      "conclusion": "SPREADING",
      "recommendation": "病情扩散，建议换用不同作用机理组的药剂。"
    }
  ]
}
```

#### 提交新观测

```typescript
// POST /api/observation
// 请求体：
{
  "orchard_id": 1,
  "captured_at": "2026-11-05T10:00:00Z",
  "image_obs_path": "obs://pomelo-agent/tracking/A1/20261105_100000.jpg",
  "detection_result": {
    "detections": [...],
    "is_healthy": false
  }
}

// 响应：
{
  "observation_id": 123,
  "trend": {
    "conclusion": "RECOVERING",
    "summary": "病斑数量从5个减少到3个，面积缩小15%。",
    "recommendation": "维持现有防治方案，注意观察是否反弹。"
  }
}
```

### 鸿蒙 APP 页面渲染

#### 病情曲线页面

```typescript
// 页面结构
struct DiseaseCurvePage {
  @State curveData: DiseaseCurve | null = null;

  build() {
    Column() {
      // 标题
      Text(`${this.curveData?.orchard_name} - ${this.diseaseLabelToChinese(this.curveData?.disease_label)}`)
        .fontSize(20)
        .fontWeight(FontWeight.Bold)

      // 病情曲线图
      LineChart({
        data: this.curveData?.data_points.map(p => ({
          date: p.date,
          lesion_count: p.lesion_count,
          total_area: p.total_area,
          conclusion: p.conclusion
        })),
        options: {
          // SPREADING 红色，STABLE 黄色，RECOVERING 绿色
          color: (conclusion) => {
            switch (conclusion) {
              case "SPREADING": return "#FF4444";
              case "STABLE": return "#FFBB33";
              case "RECOVERING": return "#00CC44";
            }
          }
        }
      })

      // 当前结论
      ConclusionBadge({ conclusion: this.curveData?.data_points.last?.conclusion })

      // 建议
      RecommendationCard({ recommendation: this.curveData?.data_points.last?.recommendation })

      // 历史观测列表
      ObservationList({ observations: this.curveData?.data_points })
    }
  }
}
```

#### 结论徽章

```typescript
struct ConclusionBadge {
  @Prop conclusion: "SPREADING" | "STABLE" | "RECOVERING" | null;

  build() {
    Row() {
      Text(this.conclusionToChinese(this.conclusion))
        .fontSize(16)
        .fontColor(this.conclusionColor(this.conclusion))
        .fontWeight(FontWeight.Bold)
    }
    .padding(12)
    .backgroundColor(this.conclusionBgColor(this.conclusion))
    .borderRadius(8)
  }

  conclusionToChinese(conclusion) {
    switch (conclusion) {
      case "SPREADING": return "⚠️ 病情扩散";
      case "STABLE": return "📊 病情稳定";
      case "RECOVERING": return "✅ 病情收敛";
      default: return "暂无数据";
    }
  }
}
```

### 颜色约定

| 结论 | 颜色 | 含义 |
|------|------|------|
| SPREADING | #FF4444（红色） | 病情扩散，需要换药 |
| STABLE | #FFBB33（黄色） | 病情稳定，继续观察 |
| RECOVERING | #00CC44（绿色） | 病情收敛，维持方案 |

## 核心 API

### compare(prev_obs, curr_obs)

比较同一地块相邻两次观测。

**参数**：
- `prev_obs`: 前一次观测（Observation 对象）
- `curr_obs`: 本次观测（Observation 对象）

**返回**：
```json
{
  "conclusion": "SPREADING",
  "prev_lesion_count": 3,
  "curr_lesion_count": 5,
  "lesion_count_change": 2,
  "prev_total_area": 1250.5,
  "curr_total_area": 1890.2,
  "total_area_change_rate": 0.511,
  "new_lesions": [{"x": 120.5, "y": 80.3}],
  "disappeared_lesions": [],
  "summary": "病斑数量从3个增加到5个，病斑总面积扩大51.1%，新增1个病斑。"
}
```

### advise_on_progress(conclusion, spray_history)

基于病情趋势给出建议。

**参数**：
- `conclusion`: 病情趋势结论（Conclusion 枚举）
- `spray_history`: 施药历史

**返回**：
```json
{
  "action": "换药",
  "reasoning": "病情扩散，当前药剂可能效果不足或存在抗药性，建议换用不同作用机理的药剂。",
  "recommendation": "近期使用过阿维菌素（第6组），建议换用不同作用机理组的药剂，如螺螨酯（IRAC 20B）或乙唑螨腈（IRAC 26）。",
  "switch_needed": true
}
```

## 业务规则

### 扩散判定条件

满足以下任一条件即为 SPREADING：
1. 病斑数量增加
2. 病斑总面积扩大 > 20%

### 收敛判定条件

满足以下任一条件即为 RECOVERING：
1. 病斑数量减少
2. 病斑总面积缩小 > 20%

### 否则为 STABLE

### 匹配规则

- 使用 IOU（Intersection over Union）匹配前后两次观测的病斑
- IOU 阈值：0.3
- 只匹配同类别病斑

## 与处方引擎的联动

当结论为 SPREADING 时，`advise_on_progress` 会建议换药。此时可调用处方引擎的 `filter_pesticides` 函数，传入：
- 病害 label
- 施药历史（含最近一次施药的作用机理组）
- 排除同组的药剂

这样就能给出"换什么药"的具体建议。

## 数据流

```
用户拍照 → 视觉识别 → 存入 observation
              ↓
         比较相邻两次观测
              ↓
         更新 disease_trend
              ↓
         渲染病情曲线（鸿蒙 APP）
              ↓
         给出趋势建议（换药/观察/维持）
```

## 注意事项

1. **时间间隔**：建议相邻两次观测间隔 7-14 天，太短无法看出趋势
2. **拍摄角度**：同一地块尽量从相同角度拍摄，便于匹配
3. **GPS 可选**：GPS 信息用于标记病斑位置，非必需
4. **图片存储**：图片存 OBS，数据库只存路径