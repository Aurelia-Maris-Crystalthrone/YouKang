// 端侧 YOLOv5s 推理封装（MindSpore Lite，ArkTS 直调）
// 对应架构中的"端侧识别"分支：离线、低延迟，田间无网可用
//
// ⚠️ 导入路径需按 DevEco Studio 实际 SDK 版本确认：
//    API 11 常见为 @ohos.ai.mindsporelite；NEXT 可能为 @kit.MindSporeLiteKit
//
// 2026-10-27 修复记录（原实现无法运行）：
//   1. 模型文件在 resources/rawfile/，但原代码直接读 filesDir，中间缺少拷贝步骤
//      → 必然加载失败；现补充 rawfile→filesDir 落盘逻辑。
//   2. 输入张量原为 NHWC [1,640,640,3]，与 converter_lite 声明的
//      --inputShape="images:1,3,640,640"(NCHW) 不一致 → 推理结果全错；现改 NCHW。
//   3. 预处理原为最近邻直接拉伸，与云端 letterbox 不一致，导致端云结果对不齐
//      → 现改为与云端同口径的 letterbox（保持长宽比 + 114 灰边填充）。
//   4. postprocess() 原为 return [] 空实现 → 现补齐 YOLOv5 解码 + 同类 NMS。

import { mindSporeLite } from '@ohos.ai.mindsporelite';
import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { Detection, DISEASE_CLASSES } from '../model/Disease';

const MODEL_FILE: string = 'yolov5s_pomelo.ms'; // 位于 resources/rawfile/
const INPUT_NAME: string = 'images';            // 必须与 converter_lite 的 inputShape 名一致
const INPUT_SIZE: number = 640;
const NUM_CLASSES: number = 4;                  // 必须与 labelmap.CLASS_NAMES 一致
const ANCHORS: number = 25200;                  // YOLOv5 640 输入的 anchor 总数
const CONF_THRESH: number = 0.25;               // 与 labelmap.CONF_THRESHOLD 一致
const IOU_THRESH: number = 0.45;
const PAD_VALUE: number = 114;                  // letterbox 灰边填充值，与云端一致

let model: mindSporeLite.Model | null = null;

/** letterbox 参数：缩放比与填充量，用于把框映射回原图坐标 */
interface LetterboxParam {
  ratio: number;
  padLeft: number;
  padTop: number;
}

/** 初始化：从 rawfile 拷贝模型到 filesDir 后加载 */
export async function initOnDeviceModel(ctx: common.UIAbilityContext): Promise<void> {
  if (model !== null) {
    return;
  }
  const targetPath: string = ctx.filesDir + '/' + MODEL_FILE;
  if (!fileIo.accessSync(targetPath)) {
    const raw: Uint8Array = await ctx.resourceManager.getRawFileContent(MODEL_FILE);
    const file: fileIo.File = fileIo.openSync(
      targetPath, fileIo.OpenMode.CREATE | fileIo.OpenMode.READ_WRITE);
    try {
      fileIo.writeSync(file.fd, raw.buffer);
    } finally {
      fileIo.closeSync(file);
    }
  }
  const liteContext: mindSporeLite.Context = new mindSporeLite.Context();
  liteContext.target = ['cpu']; // 真机可改为 ['nnrt'] 启用 NPU（实机验证通过后再切换）
  model = await mindSporeLite.loadModelFromFile(targetPath, liteContext);
}

/** 释放模型（页面销毁时调用） */
export function releaseOnDeviceModel(): void {
  model = null;
}

/**
 * 端侧推理
 * @param rgba 图像 RGBA 像素（相机帧 / 选图解码结果）
 * @param width 原图宽
 * @param height 原图高
 */
export async function detectOnDevice(
  rgba: ArrayBuffer, width: number, height: number): Promise<Detection[]> {
  if (!model) {
    throw new Error('OnDevice model not initialized');
  }
  const param: LetterboxParam = letterboxParams(width, height);
  const input: Float32Array = preprocess(rgba, width, height, param);

  const inputTensor: mindSporeLite.MSTensor = new mindSporeLite.MSTensor(
    INPUT_NAME,
    new Int32Array([1, 3, INPUT_SIZE, INPUT_SIZE]), // NCHW，与 converter_lite 一致
    mindSporeLite.DataType.FLOAT32
  );
  inputTensor.setData(input.buffer);

  const outputs: mindSporeLite.MSTensor[] = model.predict([inputTensor]);
  return postprocess(outputs, width, height, param);
}

/** 计算 letterbox 缩放比与填充量，与云端 _letterbox() 同口径 */
function letterboxParams(srcW: number, srcH: number): LetterboxParam {
  const ratio: number = Math.min(INPUT_SIZE / srcH, INPUT_SIZE / srcW);
  const newW: number = Math.round(srcW * ratio);
  const newH: number = Math.round(srcH * ratio);
  return {
    ratio: ratio,
    padLeft: Math.round((INPUT_SIZE - newW) / 2.0),
    padTop: Math.round((INPUT_SIZE - newH) / 2.0)
  };
}

/** 预处理：RGBA → letterbox 缩放 + NCHW float32[0,1] */
function preprocess(data: ArrayBuffer, w: number, h: number, param: LetterboxParam): Float32Array {
  const src: Uint8Array = new Uint8Array(data);
  const dst: Float32Array = new Float32Array(3 * INPUT_SIZE * INPUT_SIZE);
  const channelSize: number = INPUT_SIZE * INPUT_SIZE;
  const invRatio: number = 1.0 / param.ratio;

  for (let y: number = 0; y < INPUT_SIZE; y++) {
    const srcY: number = (y - param.padTop) * invRatio;
    for (let x: number = 0; x < INPUT_SIZE; x++) {
      const srcX: number = (x - param.padLeft) * invRatio;
      let r: number = PAD_VALUE;
      let g: number = PAD_VALUE;
      let b: number = PAD_VALUE;
      if (srcX >= 0 && srcX < w && srcY >= 0 && srcY < h) {
        const si: number = (Math.floor(srcY) * w + Math.floor(srcX)) * 4;
        r = src[si];
        g = src[si + 1];
        b = src[si + 2];
      }
      const di: number = y * INPUT_SIZE + x;
      dst[di] = r / 255.0;                    // R
      dst[channelSize + di] = g / 255.0;      // G
      dst[2 * channelSize + di] = b / 255.0;  // B
    }
  }
  return dst;
}

/** YOLOv5 输出解码 + 置信度过滤 + 同类 NMS，坐标还原到原图像素系 */
function postprocess(
  outputs: mindSporeLite.MSTensor[], ow: number, oh: number,
  param: LetterboxParam): Detection[] {
  if (outputs.length === 0) {
    return [];
  }
  const raw: Float32Array = new Float32Array(outputs[0].getData() as ArrayBuffer);
  const stride: number = 5 + NUM_CLASSES;
  const total: number = ANCHORS * stride;
  if (raw.length < total) {
    throw new Error(`unexpected output size: ${raw.length}, expected >= ${total}`);
  }
  // 兼容两种布局：last-dim 连续 [1,25200,5+nc] 与 channel-first [1,5+nc,25200]
  const channelFirst: boolean = outputs[0].shape.length >= 2 && outputs[0].shape[1] === stride;

  const boxes: number[][] = [];
  const scores: number[] = [];
  const classIds: number[] = [];

  for (let a: number = 0; a < ANCHORS; a++) {
    let bestScore: number = 0;
    let bestClass: number = 0;
    for (let c: number = 0; c < NUM_CLASSES; c++) {
      const v: number = channelFirst ? raw[(5 + c) * ANCHORS + a] : raw[a * stride + 5 + c];
      if (c === 0 || v > bestScore) {
        bestScore = v;
        bestClass = c;
      }
    }
    const obj: number = channelFirst ? raw[4 * ANCHORS + a] : raw[a * stride + 4];
    const conf: number = obj * bestScore;
    if (conf <= CONF_THRESH) {
      continue;
    }
    const bx: number = channelFirst ? raw[a] : raw[a * stride];
    const by: number = channelFirst ? raw[ANCHORS + a] : raw[a * stride + 1];
    const bw: number = channelFirst ? raw[2 * ANCHORS + a] : raw[a * stride + 2];
    const bh: number = channelFirst ? raw[3 * ANCHORS + a] : raw[a * stride + 3];

    // xywh(640 系) → xyxy(原图系)
    const x1: number = ((bx - bw / 2.0) * INPUT_SIZE - param.padLeft) / param.ratio;
    const y1: number = ((by - bh / 2.0) * INPUT_SIZE - param.padTop) / param.ratio;
    const x2: number = ((bx + bw / 2.0) * INPUT_SIZE - param.padLeft) / param.ratio;
    const y2: number = ((by + bh / 2.0) * INPUT_SIZE - param.padTop) / param.ratio;
    boxes.push([clamp(x1, 0, ow), clamp(y1, 0, oh), clamp(x2, 0, ow), clamp(y2, 0, oh)]);
    scores.push(conf);
    classIds.push(bestClass);
  }

  const keep: number[] = classNms(boxes, scores, classIds, IOU_THRESH);
  const result: Detection[] = [];
  for (let i: number = 0; i < keep.length; i++) {
    const k: number = keep[i];
    const b: number[] = boxes[k];
    const info = DISEASE_CLASSES[classIds[k]];
    result.push({
      label: info ? info.key : String(classIds[k]),
      labelName: info ? info.name : String(classIds[k]),
      confidence: scores[k],
      x: b[0],
      y: b[1],
      width: b[2] - b[0],
      height: b[3] - b[1],
      source: 'onDevice'
    });
  }
  return result;
}

/** 同类内贪心 NMS，返回保留索引 */
function classNms(
  boxes: number[][], scores: number[], classIds: number[], iouThresh: number): number[] {
  const keep: number[] = [];
  const visited: boolean[] = new Array<boolean>(boxes.length).fill(false);
  for (let i: number = 0; i < boxes.length; i++) {
    if (visited[i]) {
      continue;
    }
    let best: number = i;
    for (let j: number = i + 1; j < boxes.length; j++) {
      if (!visited[j] && scores[j] > scores[best]) {
        best = j;
      }
    }
    keep.push(best);
    visited[best] = true;
    for (let j: number = 0; j < boxes.length; j++) {
      if (visited[j] || classIds[j] !== classIds[best]) {
        continue;
      }
      if (iou(boxes[best], boxes[j]) > iouThresh) {
        visited[j] = true;
      }
    }
  }
  return keep;
}

function iou(a: number[], b: number[]): number {
  const ltX: number = Math.max(a[0], b[0]);
  const ltY: number = Math.max(a[1], b[1]);
  const rbX: number = Math.min(a[2], b[2]);
  const rbY: number = Math.min(a[3], b[3]);
  const inter: number = Math.max(0, rbX - ltX) * Math.max(0, rbY - ltY);
  const areaA: number = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1]);
  const areaB: number = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const union: number = areaA + areaB - inter;
  return union > 0 ? inter / union : 0;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}
