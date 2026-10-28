// 主页面：拍照/选图 → 质量门 → 端云路由识别 → 结果展示
//
// 2026-10-27 重写要点（原实现 pickImage 只改了一句提示文字）：
//   1. 接入 photoAccessHelper 真实选图并解码为 RGBA；
//   2. 加入端侧质量门（模糊/过曝/非叶片当场拒绝）；
//   3. 端云路由有了真实策略，而不是"两路都跑一下"：
//      端侧高置信 → 直接出结果（省流量低时延，田间无网可用）
//      端侧低置信或 top-2 接近 → 上传云端智能体复核 + 取防治建议
//   4. top-2 分差过小时不硬下结论，改为发起鉴别性追问；
//   5. 命中检疫性病害（黄龙病）时强制提示上报。

import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { image } from '@kit.ImageKit';
import { photoAccessHelper } from '@kit.MediaLibraryKit';
import { callAgent } from '../common/AgentClient';
import { initOnDeviceModel, detectOnDevice } from '../common/OnDeviceDetector';
import { evaluateImageQuality } from '../common/ImageQuality';
import {
  Detection, RecognizeResult, DISEASE_CLASSES, HEALTHY_KEY,
  QUARANTINE_KEYS, DISCRIMINATIVE_QUESTIONS, AMBIGUOUS_MARGIN
} from '../model/Disease';

const CLOUD_CONF_THRESHOLD: number = 0.80;   // 端侧高于此值不再上传云端
const LOW_CONF_THRESHOLD: number = 0.45;     // 低于此值必须走云端复核

@Entry
@Component
struct Index {
  @State imageSrc: string = '';
  @State detections: Detection[] = [];
  @State tip: string = '请拍照或选择柚子叶片图片';
  @State adviceText: string = '';
  @State followUp: string = '';
  @State loading: boolean = false;
  @State useCloud: boolean = true;
  @State modelReady: boolean = false;
  private ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
  private pixelBuffer: ArrayBuffer | null = null;
  private imageWidth: number = 0;
  private imageHeight: number = 0;

  aboutToAppear(): void {
    initOnDeviceModel(this.ctx)
      .then(() => { this.modelReady = true; })
      .catch((e: Error) => {
        this.modelReady = false;
        console.error('init model failed: ' + e.message);
      });
  }

  /** 选图：photoAccessHelper → PixelMap → RGBA */
  async pickImage(): Promise<void> {
    try {
      const picker: photoAccessHelper.PhotoViewPicker = new photoAccessHelper.PhotoViewPicker();
      const picked: photoAccessHelper.PhotoSelectResult = await picker.select({
        maxSelectNumber: 1,
        MIMEType: photoAccessHelper.PhotoViewMIMETypes.IMAGE_TYPE
      });
      if (picked.photoUris.length === 0) {
        return;
      }
      const uri: string = picked.photoUris[0];
      const file: fileIo.File = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      const source: image.ImageSource = image.createImageSource(file.fd);
      const pixelMap: image.PixelMap = await source.createPixelMap();
      fileIo.closeSync(file);

      this.imageWidth = pixelMap.getImageInfoSync().size.width;
      this.imageHeight = pixelMap.getImageInfoSync().size.height;
      const buffer: ArrayBuffer = new ArrayBuffer(pixelMap.getPixelBytesNumber());
      await pixelMap.readPixelsToBuffer(buffer);
      this.pixelBuffer = buffer;
      this.imageSrc = uri;
      this.detections = [];
      this.adviceText = '';
      this.followUp = '';
      this.tip = '已选择图片，点击开始识别';
    } catch (e) {
      const err: Error = e as Error;
      this.tip = '选图失败：' + err.message;
    }
  }

  /** 端云路由识别 */
  async recognize(): Promise<void> {
    if (this.pixelBuffer === null) {
      this.tip = '请先选择叶片图片';
      return;
    }
    this.loading = true;
    this.followUp = '';
    try {
      // 1) 端侧质量门：不合格直接拒绝，不浪费推理算力
      const quality = evaluateImageQuality(this.pixelBuffer, this.imageWidth, this.imageHeight);
      if (!quality.usable) {
        this.tip = '照片不可用：' + quality.reason + '。' + quality.guidance;
        return;
      }

      // 2) 端侧推理（离线优先）
      let local: Detection[] = [];
      if (this.modelReady) {
        local = await detectOnDevice(this.pixelBuffer, this.imageWidth, this.imageHeight);
      }

      // 3) 路由决策
      const needCloud: boolean = this.useCloud && (
        local.length === 0 ||
        local[0].confidence < LOW_CONF_THRESHOLD ||
        local[0].confidence < CLOUD_CONF_THRESHOLD ||
        this.isAmbiguous(local[0]));

      if (needCloud) {
        const result: RecognizeResult = await callAgent('', '请识别这张柚子叶片的病害并给出防治建议');
        this.detections = result.detections.length > 0 ? result.detections : local;
        this.adviceText = result.rawText ?? '';
        this.tip = '云端智能体已复核';
      } else {
        this.detections = local;
        this.adviceText = '';
        this.tip = '端侧识别完成（离线）';
      }

      // 4) 结论后处理：健康 / 不确定性追问 / 检疫上报
      this.applyConclusionRules();
    } catch (e) {
      const err: Error = e as Error;
      this.tip = '识别失败：' + err.message;
    } finally {
      this.loading = false;
    }
  }

  /** top-2 分差过小 → 不硬下结论，发起鉴别性追问 */
  private isAmbiguous(d: Detection): boolean {
    if (!d.top2 || d.top2.length < 2) {
      return false;
    }
    return (d.top2[0].score - d.top2[1].score) < AMBIGUOUS_MARGIN;
  }

  private applyConclusionRules(): void {
    if (this.detections.length === 0) {
      this.tip = '未检出病斑，叶片看起来是健康的（建议日常巡查）';
      return;
    }
    const top: Detection = this.detections[0];

    // 检疫性病害强制上报提示（黄龙病）
    if (QUARANTINE_KEYS.indexOf(top.label) >= 0) {
      this.adviceText = '⚠️ 疑似检疫性病害，请勿自行处理，立即联系当地植保站上报。\n' + this.adviceText;
    }

    // 不确定时改为追问，而不是给出可能错误的结果
    if (this.isAmbiguous(top) && top.top2 && top.top2.length >= 2) {
      const key: string = top.top2[0].label + '|' + top.top2[1].label;
      const q: string = DISCRIMINATIVE_QUESTIONS[key] ??
        '这两个病害比较像，能再拍一张病斑的近距离照片吗？';
      this.followUp = q;
      this.tip = '结果不太确定，需要确认一下';
    }
  }

  private labelName(label: string): string {
    if (label === HEALTHY_KEY) {
      return '健康';
    }
    const keys: string[] = Object.keys(DISEASE_CLASSES);
    for (let i: number = 0; i < keys.length; i++) {
      if (DISEASE_CLASSES[Number(keys[i])].key === label) {
        return DISEASE_CLASSES[Number(keys[i])].name;
      }
    }
    return label;
  }

  build() {
    Column({ space: 10 }) {
      Text('柚康 · 柚子病虫害识别').fontSize(22).fontWeight(FontWeight.Bold)

      Stack() {
        if (this.imageSrc) {
          Image(this.imageSrc).width('100%').height(280).objectFit(ImageFit.Contain)
        } else {
          Text('预览区').fontSize(14).fontColor(Color.Gray)
        }
        ForEach(this.detections, (d: Detection) => {
          Rect()
            .position({ x: d.x, y: d.y })
            .width(d.width).height(d.height)
            .stroke(Color.Red).strokeWidth(2)
        }, (d: Detection) => d.label + d.x + d.y)
      }.width('100%').height(280).border({ width: 1, color: Color.Gray })

      Row({ space: 8 }) {
        Button('拍照/选图').onClick(() => this.pickImage())
        Button(this.loading ? '识别中...' : '开始识别')
          .onClick(() => this.recognize())
          .enabled(!this.loading)
      }

      Row({ space: 8 }) {
        Toggle({ type: ToggleType.Switch, isOn: this.useCloud })
          .onChange((v: boolean) => { this.useCloud = v; })
        Text('允许云端复核（关闭则纯端侧离线）').fontSize(12)
      }

      Text(this.tip).fontSize(14).fontColor(Color.Gray)

      ForEach(this.detections, (d: Detection) => {
        Row({ space: 6 }) {
          Text(this.labelName(d.label)).fontSize(14).fontWeight(FontWeight.Medium)
          Text((d.confidence * 100).toFixed(0) + '%').fontSize(12).fontColor(Color.Gray)
          Text(d.source === 'onDevice' ? '端侧' : '云端').fontSize(11).fontColor('#2563EB')
        }
      }, (d: Detection) => d.label + d.x + d.y + d.source)

      if (this.followUp) {
        Text('追问：' + this.followUp)
          .fontSize(14).fontColor('#D97706')
          .backgroundColor('#FEF3C7').padding(10).borderRadius(6)
      }

      if (this.adviceText) {
        Text(this.adviceText).fontSize(13).padding(10)
          .backgroundColor('#F3F4F6').borderRadius(6)
      }

      Blank()
      Text(this.modelReady ? '端侧模型已就绪' : '端侧模型未就绪（将走云端）')
        .fontSize(11).fontColor(Color.Gray)
    }
    .width('100%').height('100%').padding(16)
  }
}
