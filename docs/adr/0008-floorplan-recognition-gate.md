# ADR-0008：户型图自动识别与人工复核契约

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

建立从已上传户型图产生可编辑墙/房间建议的稳定契约，证明任务身份、尺度标定、
置信度、失败状态和可视化叠加图可与现有 Pascal 人工纠错流程衔接。

## 开源与许可结论

1. CubiCasa5K 有 5,000 张、80+ 类密集多边形标注，但官方仓库许可为 CC BY-NC 4.0，
   现成数据与预训练权重不进入商业产品。
2. RoomFormer 官方代码为 MIT，其 polygon structured prediction 方向可作为后续模型参考；
   但默认数据是 RGB-D/3D scan 投影的 density map，不等价于普通彩色户型图。
3. Pascal 上游的 MCP vision sampling 工具是有用的对照实验，但没有冻结模型、数据集与
   几何评测，不担任产品权威识别器。
4. 首个闸门使用 Apache-2.0 的 OpenCV 4.x 代码路径，仅消费项目自建受控 fixture，
   不捆绑任何外部数据或权重。

## 决定

1. `RecognitionBackend` 是可替换边界。当前 `opencv-axis-aligned-baseline-v1` 先做 Otsu
   二值化，用水平/垂直形态学核提取墙体，再从闭合自由空间的连通域生成房间候选。
2. 请求必须同时指定 `sceneRevision`、已进入该场景的 `assetId` 和显式
   `planWidthMeters`。任务身份包含上述全部输入与 pipeline version。
3. 建议坐标为米制 `plan-bottom-left` / `x-right-z-up`。墙建议直接对应 Pascal wall
   所需的 `start/end/thickness`；房间候选直接对应 Zone polygon，但不提前生成场景 node id/父子关系。
4. 成功状态是 `review_required`，不是 `ready`。识别器永远不直接修改权威 scene JSON；
   后续编辑器必须允许逐条接受、拒绝或修正，然后通过现有 revision 冲突控制保存。
5. manifest 包含整体/单项 confidence、墙/房间/开口列表、像素尺度、Otsu 阈值、
   结构像素比、`reviewReasons[]` 与可校验 overlay PNG。当前对门窗和房型语义输出空列表并显式声明未支持。
6. 解码失败、无墙或墙体过少都进入 `failed`；失败 manifest 不包含墙/房间或 overlay，
   人工描绘流程继续可用。

## 真实验证

- 500×400 双房间受控 PNG 通过真实 HTTP 完成上传、scene 绑定、`processing →
  review_required` 和 overlay 下载。
- 稳定输出 5 条墙、2 个房间、41.3 px/m、约 63.26 m² 内部面积；叠加图中红色墙中心线与
  绿色房间边界均与黑色 fixture 对齐。
- 空白图显式失败，不生成建议或 overlay；错误 revision、非场景图片和非法比例均在 API 边界被拒绝。
- FastAPI 自动测试增至 59 项并全部通过。

## 已知限制与下一闸门

- 当前只适合背景干净、对比强、主要墙体轴对齐且房间闭合的标准图；彩色家具、文字、尺寸标注、
  斜墙/曲墙、扫描噪声、门窗符号和复杂断裂墙均需要合法真实数据集上的模型基线。
- 下一闸门是编辑器复核 UI，不是直接把当前算法宣称为全自动；产品指标应使用“人工修正中位时间”与合法真实测试集的墙/门窗/房间指标。
