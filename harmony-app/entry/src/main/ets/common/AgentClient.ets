// 云端智能体 API 调用封装
// 对应架构中的"云端智能体"分支：拍照后把图片/描述发给华为云智能体，拿回识别+防治建议
import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { RecognizeResult, Treatment, Detection, Candidate, DISEASE_CLASSES, HEALTHY_KEY } from '../model/Disease';

// ⚠️ 以下内容需核实（取决于 ModelArts Studio Agent开发 部署形态 + 是否接 APIG）
const AGENT_API_URL = 'https://{你的智能体API域名}/v1/agents/{agentId}/chat'; // 需核实
const AGENT_AUTH_TOKEN = '{从配置读取，勿硬编码进 git}';                       // 需核实鉴权方式

/**
 * 调用云端智能体：上传图片（base64 或 图片 URL）并获取自然语言防治建议
 * @param base64Image 图片 base64（不含 data: 前缀）
 * @param prompt 用户问题，如 "请识别这张柚子叶片的病害并给出防治建议"
 */
export async function callAgent(base64Image: string, prompt: string): Promise<RecognizeResult> {
  let httpRequest = http.createHttp();
  try {
    const resp: http.HttpResponse = await httpRequest.request(AGENT_API_URL, {
      method: http.RequestMethod.POST,
      header: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + AGENT_AUTH_TOKEN // 或 'X-Apig-Appcode': appcode
      },
      extraData: JSON.stringify({
        messages: [
          {
            role: 'user',
            content: prompt,
            // 多模态：图片随消息携带（具体字段需按平台文档调整）
            image_base64: base64Image
          }
        ]
      }),
      expectDataType: http.HttpDataType.STRING,
      connectTimeout: 15000,
      readTimeout: 30000
    });

    if (resp.responseCode === 200) {
      const data = JSON.parse(resp.result as string);
      // 解析逻辑需按智能体实际返回结构对齐（下面为示例映射）
      return mapAgentResponse(data);
    } else {
      throw new Error('Agent API error: ' + resp.responseCode);
    }
  } catch (err) {
    const e = err as BusinessError;
    console.error('callAgent failed: ' + JSON.stringify(e));
    throw err;
  } finally {
    httpRequest.destroy();
  }
}

/**
 * 将智能体返回映射为本地 RecognizeResult。
 *
 * 原实现为固定返回空的占位（等于云端链路永远拿不到结果）。
 * ModelArts Studio 不同形态（单智能体 / 工作流）的返回结构字段名不统一，
 * 这里做宽容解析：递归查找 detections / text / treatments，
 * 命中不到时不抛异常，而是把原文塞进 rawText 供兜底展示。
 */
function mapAgentResponse(data: Object): RecognizeResult {
  const root: Record<string, Object> = data as Record<string, Object>;
  const detections: Detection[] = parseDetections(findArray(root, 'detections'));
  const treatments: Treatment[] = parseTreatments(findArray(root, 'treatments'));
  const rawText: string = findString(root, ['reply', 'content', 'text', 'answer', 'output']);

  return {
    detections: detections,
    treatments: treatments,
    fromCloud: true,
    rawText: rawText.length > 0 ? rawText : JSON.stringify(data)
  };
}

function parseDetections(list: Object[]): Detection[] {
  const result: Detection[] = [];
  for (let i: number = 0; i < list.length; i++) {
    const item: Record<string, Object> = list[i] as Record<string, Object>;
    const label: string = findString(item, ['label', 'class', 'name', 'disease']);
    const bbox: number[] = findNumberArray(item, ['bbox', 'box', 'rect']);
    if (label.length === 0 || bbox.length < 4) {
      continue;
    }
    const conf: number = findNumber(item, ['confidence', 'score', 'conf']);
    const top2: Candidate[] = parseCandidates(findArray(item, 'top2'));
    let x: number = bbox[0];
    let y: number = bbox[1];
    let w: number = bbox[2] - bbox[0];
    let h: number = bbox[3] - bbox[1];
    // 兼容 [x, y, w, h] 布局：当第三/四项明显小于第一/二项时按 xywh 解析
    if (bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) {
      w = bbox[2];
      h = bbox[3];
    }
    result.push({
      label: label,
      labelName: labelNameOf(label),
      confidence: conf,
      x: x,
      y: y,
      width: w,
      height: h,
      source: 'cloud',
      top2: top2
    });
  }
  return result;
}

function parseCandidates(list: Object[]): Candidate[] {
  const result: Candidate[] = [];
  for (let i: number = 0; i < list.length; i++) {
    const item: Record<string, Object> = list[i] as Record<string, Object>;
    const label: string = findString(item, ['label', 'class', 'name']);
    if (label.length === 0) {
      continue;
    }
    result.push({ label: label, score: findNumber(item, ['score', 'confidence']) });
  }
  return result;
}

function parseTreatments(list: Object[]): Treatment[] {
  const result: Treatment[] = [];
  for (let i: number = 0; i < list.length; i++) {
    const item: Record<string, Object> = list[i] as Record<string, Object>;
    result.push({
      disease: findString(item, ['disease', 'name', 'label']),
      symptom: findString(item, ['symptom', 'desc', 'description']),
      suggestion: findString(item, ['suggestion', 'control', 'advice', 'treatment']),
      period: findString(item, ['period', 'phi', 'window', 'note'])
    });
  }
  return result;
}

function labelNameOf(key: string): string {
  const keys: string[] = Object.keys(DISEASE_CLASSES);
  for (let i: number = 0; i < keys.length; i++) {
    if (DISEASE_CLASSES[Number(keys[i])].key === key) {
      return DISEASE_CLASSES[Number(keys[i])].name;
    }
  }
  return key === HEALTHY_KEY ? '健康' : key;
}

/** 在对象（含一层嵌套 data/result/output）中按候选键名查找字符串 */
function findString(obj: Record<string, Object>, keys: string[]): string {
  for (let k: number = 0; k < keys.length; k++) {
    const v: Object = obj[keys[k]];
    if (typeof v === 'string') {
      return v as string;
    }
  }
  for (let k: number = 0; k < keys.length; k++) {
    const nested: Object = obj[keys[k]];
    if (typeof nested === 'object' && nested !== null) {
      const found: string = findString(nested as Record<string, Object>, ['content', 'text']);
      if (found.length > 0) {
        return found;
      }
    }
  }
  for (let i: number = 0; i < NESTED_KEYS.length; i++) {
    const nested: Object = obj[NESTED_KEYS[i]];
    if (typeof nested === 'object' && nested !== null) {
      const found: string = findString(nested as Record<string, Object>, keys);
      if (found.length > 0) {
        return found;
      }
    }
  }
  return '';
}

function findNumber(obj: Record<string, Object>, keys: string[]): number {
  for (let k: number = 0; k < keys.length; k++) {
    const v: Object = obj[keys[k]];
    if (typeof v === 'number') {
      return v as number;
    }
  }
  return 0;
}

function findNumberArray(obj: Record<string, Object>, keys: string[]): number[] {
  for (let k: number = 0; k < keys.length; k++) {
    const v: Object = obj[keys[k]];
    if (Array.isArray(v) && v.length >= 4) {
      const out: number[] = [];
      for (let i: number = 0; i < v.length; i++) {
        out.push(Number(v[i]));
      }
      return out;
    }
  }
  return [];
}

function findArray(obj: Record<string, Object>, key: string): Object[] {
  const direct: Object = obj[key];
  if (Array.isArray(direct)) {
    return direct as Object[];
  }
  for (let i: number = 0; i < NESTED_KEYS.length; i++) {
    const nested: Object = obj[NESTED_KEYS[i]];
    if (typeof nested === 'object' && nested !== null) {
      const found: Object[] = findArray(nested as Record<string, Object>, key);
      if (found.length > 0) {
        return found;
      }
    }
  }
  return [];
}

const NESTED_KEYS: string[] = ['data', 'result', 'output', 'choices', 'message'];
