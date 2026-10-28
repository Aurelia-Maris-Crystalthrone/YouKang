// 拍照质量守门员（纯 ArkTS，无需模型）
// 作用：在送入模型前先判断照片是否"可用"，不合格当场拒绝并给出具体指引。
//
// 为什么需要：田间实测中识别不准绝大多数不是模型问题，而是照片问题——
// 逆光、糊焦、病斑太小、拍的是地面而不是叶片。与其让模型瞎猜，
// 不如在端侧直接拦下来，成本极低（几十行）而体验提升巨大。
//
// 这也是"端云协同"的真实分工体现：端侧做感知把关，云端做认知决策。

export interface QualityResult {
  usable: boolean;      // 是否可送入模型
  reason: string;       // 不合格原因（可直接展示给柚农）
  guidance: string;     // 具体改进指引
  sharpness: number;    // 清晰度（拉普拉斯方差近似），越大越清晰
  brightness: number;   // 平均亮度 0~255
  leafRatio: number;    // 绿色像素占比，用于判断是否拍到了叶片
}

const SHARPNESS_MIN: number = 12;    // 低于此值判定模糊（需按真机实拍校准）
const BRIGHTNESS_MIN: number = 40;   // 过暗
const BRIGHTNESS_MAX: number = 225;  // 过曝
const LEAF_RATIO_MIN: number = 0.08; // 绿色占比过低，可能拍的不是叶片

/**
 * 评估照片质量
 * @param rgba RGBA 像素
 * @param width 宽
 * @param height 高
 */
export function evaluateImageQuality(rgba: ArrayBuffer, width: number, height: number): QualityResult {
  const data: Uint8Array = new Uint8Array(rgba);
  // 大图按步长抽样，保证端侧实时性（每 4 行 4 列取一个点）
  const step: number = 4;
  let sumBrightness: number = 0;
  let greenCount: number = 0;
  let sampled: number = 0;
  let sharpAccum: number = 0;
  let sharpSamples: number = 0;

  for (let y: number = step; y < height - step; y += step) {
    for (let x: number = step; x < width - step; x += step) {
      const idx: number = (y * width + x) * 4;
      const r: number = data[idx];
      const g: number = data[idx + 1];
      const b: number = data[idx + 2];
      const lum: number = 0.299 * r + 0.587 * g + 0.114 * b;
      sumBrightness += lum;
      sampled++;

      // 绿色判定：绿色通道显著高于红蓝，且不是灰白
      if (g > r + 10 && g > b + 10 && g > 40) {
        greenCount++;
      }

      // 拉普拉斯近似：中心点与四邻域差异，衡量局部对比（清晰度）
      const right: number = (y * width + (x + step)) * 4;
      const down: number = ((y + step) * width + x) * 4;
      const d1: number = lum - (0.299 * data[right] + 0.587 * data[right + 1] + 0.114 * data[right + 2]);
      const d2: number = lum - (0.299 * data[down] + 0.587 * data[down + 1] + 0.114 * data[down + 2]);
      sharpAccum += d1 * d1 + d2 * d2;
      sharpSamples++;
    }
  }

  if (sampled === 0) {
    return { usable: false, reason: '图片解析失败', guidance: '请重新拍摄', sharpness: 0, brightness: 0, leafRatio: 0 };
  }

  const brightness: number = sumBrightness / sampled;
  const leafRatio: number = greenCount / sampled;
  const sharpness: number = sharpSamples > 0 ? sharpAccum / sharpSamples : 0;

  if (sharpness < SHARPNESS_MIN) {
    return {
      usable: false, reason: '照片太模糊',
      guidance: '请拿稳手机、等相机对焦完成后再拍，或擦一下镜头',
      sharpness: sharpness, brightness: brightness, leafRatio: leafRatio
    };
  }
  if (brightness < BRIGHTNESS_MIN) {
    return {
      usable: false, reason: '光线太暗',
      guidance: '请换个明亮的角度，避免逆光拍摄',
      sharpness: sharpness, brightness: brightness, leafRatio: leafRatio
    };
  }
  if (brightness > BRIGHTNESS_MAX) {
    return {
      usable: false, reason: '画面过曝',
      guidance: '请避开阳光直射，在树荫下重拍',
      sharpness: sharpness, brightness: brightness, leafRatio: leafRatio
    };
  }
  if (leafRatio < LEAF_RATIO_MIN) {
    return {
      usable: false, reason: '没拍到叶片',
      guidance: '请把镜头对准叶片，让叶片占满画面',
      sharpness: sharpness, brightness: brightness, leafRatio: leafRatio
    };
  }
  return {
    usable: true, reason: '', guidance: '',
    sharpness: sharpness, brightness: brightness, leafRatio: leafRatio
  };
}
