// 病害数据类型定义（与 RDS 表 / 智能体返回结构保持一致）

/** 单个候选类别（云端服务返回的 top2 用） */
export interface Candidate {
  label: string;
  score: number;
}

/** 单张检测框 */
export interface Detection {
  label: string;          // 病害类别，如 "red_spider_mite" / "anthracnose" / "canker" / "greening"
  labelName: string;      // 中文名，如 "红蜘蛛" / "炭疽病" / "溃疡病" / "黄龙病"
  confidence: number;     // 置信度 0~1
  x: number;              // 左上角 x（像素）
  y: number;              // 左上角 y（像素）
  width: number;          // 框宽
  height: number;         // 框高
  source: 'onDevice' | 'cloud'; // 来源：端侧 / 云端
  top2?: Candidate[];     // 次优类别：用于判断是否发起鉴别性追问
}

/** 防治建议（来自 RDS 或智能体） */
export interface Treatment {
  disease: string;        // 病害类别
  symptom: string;        // 典型症状
  suggestion: string;     // 防治建议（药剂/农事）
  period: string;         // 施药周期/注意事项
}

/** 识别结果聚合 */
export interface RecognizeResult {
  detections: Detection[];
  treatments: Treatment[];
  fromCloud: boolean;     // 是否走了云端智能体
  rawText?: string;       // 云端智能体原始自然语言回复（可选展示）
}

/** 目标病害类别映射（必须与 labelmap.py CLASS_NAMES 顺序严格一致） */
export const DISEASE_CLASSES: Record<number, { key: string; name: string }> = {
  0: { key: 'red_spider_mite', name: '红蜘蛛' },
  1: { key: 'anthracnose', name: '炭疽病' },
  2: { key: 'canker', name: '溃疡病' },
  3: { key: 'greening', name: '黄龙病' }
};

/** 负样本结论：模型无检测框时判定为健康（healthy 不占类别编号） */
export const HEALTHY_KEY: string = 'healthy';

/** 检疫性病害：命中时必须提示上报，不能只给防治建议 */
export const QUARANTINE_KEYS: string[] = ['greening'];

/**
 * 鉴别性追问题库：best 与 second 置信度接近时使用。
 * 对应《行动指南》第二章各病害的"区分点"，把区分特征转成柚农听得懂的问题。
 */
export const DISCRIMINATIVE_QUESTIONS: Record<string, string> = {
  'canker|anthracnose': '病斑摸起来是隆起的还是平塌的？隆起粗糙多为溃疡病，平塌多为炭疽病。',
  'anthracnose|canker': '病斑周围有一圈黄晕吗？有黄晕多为溃疡病，无黄晕且有轮纹小黑点多为炭疽病。',
  'greening|canker': '叶片是斑驳黄化还是局部病斑？斑驳黄化且新叶先黄多为黄龙病。',
  'canker|greening': '叶片是斑驳黄化还是局部病斑？斑驳黄化且新叶先黄多为黄龙病。',
  'red_spider_mite|healthy': '翻到叶背看看，有没有针尖大的红色小虫或细密蛛丝？',
  'healthy|red_spider_mite': '叶面有没有密布的针尖大灰白色失绿斑点？'
};

/** best 与 second 分差低于此值时，不直接下结论，改为追问 */
export const AMBIGUOUS_MARGIN: number = 0.15;
