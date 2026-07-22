# ADR-0021：真实户型主链路可靠性报告

## 状态

已接受，2026-07-22。

## 背景

ADR-0020 已证明一张受控直墙户型可以从上传走到客户三风格 Viewer，但墙/房间的 precision、
recall 和单张演示都不能回答产品最重要的问题：一批合法真实户型中，有多少最终能生成可发布
的 3D 方案，以及失败发生在哪一段。

## 决策

1. 可靠性报告直接消费 ADR-0010 的 `EvaluationDataset`，继续执行商业权利、图片 SHA-256、
   complete/pending 和坐标系校验，不创建第二套样本格式。
2. 每个 complete 样本在临时目录运行真实 OpenCV、内存 RecognitionManifest、baseline 权威
   Scene、结构 GLB、ArtifactStore + glTF-Transform v4 和目录内全部风格 layout；不启动 API，
   不写入用户项目。
3. 状态固定为 `pending`、`invalid`、`recognition_failed`、`scene_failed`、`artifact_failed`、
   `layout_failed`、`publishable`。每个失败只归到最先阻断客户交付的阶段。
4. publishable 与线上 baseline 保持一致：产物 ready，且每个目录风格至少有一个 furnished
   room。layout 的 ready/partial、房间数和 placement 数继续保留，便于后续收紧质量门槛。
5. `publishableRate` 以所有 complete 样本为分母。invalid 计入失败，pending 不参与；这样既不
   隐藏数据完整性问题，也不把未完成标注混入算法成功率。
6. reportId 绑定数据集规范化摘要、样本图片摘要、识别/baseline/artifact/layout 管线、全部
   风格和资产目录版本，但不绑定运行耗时；同一输入和版本重跑保持稳定。

## 验收结果

- 自动测试覆盖 publishable、pending、invalid、recognition/scene/artifact/layout failed，
  定向测试 3/3 通过。
- 项目自有 500×400 双房 fixture 使用真实 Node worker 完成：OpenCV 0.78、5 墙/2 房，GLB
  2808 B→3252 B，现代/北欧/暖木三风格均 ready、各 2 房/11 placements，约 644 ms。
- 上述 1/1 只证明工具与受控主线可执行。仓库尚无正式 20～50 张 complete manifest，因此不
  发布真实户型成功率，也不据此宣称达到 80% 产品目标。

## 下一步

- 继续由人工完成权利审核、真值标注和第二人复核，将合法样本晋级到正式 manifest。
- 样本达到可统计规模后同时运行几何报告和主链路报告，按失败数量优先升级门窗、斜墙、房间
  语义或复核入口，而不是凭单张视觉印象选择算法方向。
