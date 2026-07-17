# 户型识别评测集

这里保存可用于商业产品评测的户型图清单和人工几何标注。数据集不是图片收集目录；每个样本在
进入评测前必须先通过来源、授权、完整性和标注审核。

## 目录约定

```text
datasets/recognition/
├── manifest.example.json       清单与标注示例
├── evaluation-dataset.schema.json
├── images/                     仅放允许再分发的已审核图片
├── private/                    不可再分发、但已获内部评测授权的本地图片
└── reports/                    本地生成的评测报告
```

`private/` 和 `reports/` 已忽略。`storageMode: repository` 的样本必须同时声明
`redistributionAllowed: true`；否则契约校验失败。`storageMode: local-only` 只表示不把图片
提交到 Git，并不能替代商业使用授权。

## 权利审核

每个样本必须记录：

- 原始标题、作者和来源页面；
- 许可证标识、许可证页面和具体权利证据页面；
- 是否确认商业评测、是否允许再分发；
- 审核人、审核日期和图片 SHA-256。

许可不清的样本保持在外部候选表，不能写成 `commercialUseConfirmed: true`。CubiCasa5K、
FloorPlanCAD 和从房产网站抓取的图片当前不进入商业评测集。明确标记 CC0 的 Smithsonian
Open Access 图片可以作为权利样本，但历史建筑图不能替代现代住宅业务样本。

## 标注规范

- 坐标系固定为米制 `plan-bottom-left-x-right-z-up-m`。
- `planWidthMeters` 是户型外边界的已知宽度，不是图片像素宽度。
- 墙体标注中心线起点、终点和实际墙厚；起终点方向不影响匹配。
- 房间多边形沿内墙可用边界顺序标注，不能自相交；同时标记房间类型。
- 门窗标注类型、中心点和净宽。
- 尚未完成双人复核的样本使用 `annotationStatus: pending`，评测报告会明确跳过。
- 标注提交自动记录识别管线和前台有效修正秒数；正式晋级时映射为 `correctionSessions`，人员和
  日期取首轮标注签名，而不是第二人几何复核签名。

默认指标阈值为墙端点 0.25 米、房间 IoU 0.5、门窗中心 0.3 米、门窗宽度 0.2 米。
报告输出墙体、房间和门窗的 precision/recall/F1，以及墙端点平均误差、房间平均 IoU 和
房间语义准确率。首版主要产品目标仍是人工修正中位时间，而不是只追求单一像素指标。

## 收集候选

下面的离线工具只从 Wikimedia Commons 官方 API 收集提供方标记为 `CC0` 或
`Public domain` 的 JPG/PNG，并生成缩略图联系表。输出始终保持 `rightsReviewStatus: pending`、
`commercialUseConfirmed: false`；提供方元数据不能替代逐文件人工审核。

```bash
cd services/api
python -m app.recognition_candidates \
  --limit 20 \
  --delay-seconds 2 \
  --output ../../datasets/recognition/private/commons-candidates/queue.json \
  --download-dir ../../datasets/recognition/private/commons-candidates/images \
  --contact-sheet ../../datasets/recognition/private/commons-candidates/contact-sheet.jpg
```

下载使用 1024 像素标准缩略图、有限 429/503 重试和可恢复文件；单项失败会写入队列后返回失败，
再次运行只补缺失文件。人工需要继续排除立面、剖面、多页拼图、比例不明和非现代住宅样本。

## 生成标注工作包

`candidate-reviews.example.json` 展示语义筛选和权利审核的独立记录。内容类型、目标域、选择原因、
已知宽度和尺度证据属于 curation；商业使用与再分发结论属于 rights。AI 辅助的图面筛选不能替代
项目负责人或权利人员签署 rights，未签署时必须保持 `status: pending`。

```bash
cd services/api
python -m app.recognition_annotation_workpack \
  --queue ../../datasets/recognition/private/commons-candidates/queue.json \
  --reviews ../../datasets/recognition/candidate-reviews.example.json \
  --candidate-id commons-190205778 \
  --image-dir ../../datasets/recognition/private/commons-candidates/images \
  --output ../../datasets/recognition/private/annotation-workpacks/commons-190205778/workpack.json \
  --overlay ../../datasets/recognition/private/annotation-workpacks/commons-190205778/overlay.png
```

工具会重新核验图片 SHA-256、字节数和可解码尺寸，并运行当前识别基线。预测放在
`suggestions` 且固定 `isGroundTruth: false`；人工真值位于独立的 `groundTruth`，初始为空。
只要权利或真值未完成，`promotionEligible` 固定为 false 并列出阻断原因。被语义筛选拒绝或
权利拒绝的候选不能生成工作包。

## 编辑与校验真值

使用 `apps/annotator` 载入工作包及其原图。标注台会再次校验图片哈希和尺寸，并将机器建议保持为
只读参考层；只有显式复制、绘制或修改的墙体、房间、门窗和房型语义会进入导出真值。具体操作见
`apps/annotator/README.md`。

导出的 `draft` 可继续编辑并恢复累计时间；新 `ready-for-review` 至少需要一面墙、标注人、日期和
大于零的有效修正时间。旧的无计时提交仍可复核，但不能晋级正式样本。交接前运行：

```bash
cd services/api
python -m app.recognition_annotation_submission \
  --workpack ../../datasets/recognition/private/annotation-workpacks/<candidate>/workpack.json \
  --annotation /path/to/<candidate>-ready-for-review.json
```

待复核不等于标注完成或权利批准。复核员可在标注台载入同一工作包、原图和待复核 JSON，导出
绑定原标注 SHA-256 的 `approved` 或 `changes-requested` review。也可用 CLI 生成：

```bash
python -m app.recognition_annotation_review review \
  --workpack ../../datasets/recognition/private/annotation-workpacks/<candidate>/workpack.json \
  --annotation /path/to/<candidate>-ready-for-review.json \
  --decision approved \
  --reviewed-by reviewer-b \
  --reviewed-at 2026-07-17 \
  --output /path/to/<candidate>-review-approved.json
```

标注人不能复核自己的提交；`changes-requested` 还必须传入 `--comment`。标注文件变化后旧 review
摘要不再匹配，必须重新复核。

权利已人工批准、图片已按存储模式放入数据集目录且 review 通过后，生成单个正式样本：

```bash
python -m app.recognition_annotation_review promote \
  --workpack ../../datasets/recognition/private/annotation-workpacks/<candidate>/workpack.json \
  --annotation /path/to/<candidate>-ready-for-review.json \
  --review /path/to/<candidate>-review-approved.json \
  --candidate-reviews ../../datasets/recognition/candidate-reviews.json \
  --dataset-root ../../datasets/recognition \
  --sample-id <sanitized-sample-id> \
  --image-path private/<candidate>.png \
  --split calibration \
  --storage-mode local-only \
  --source-title "Sanitized source title" \
  --source-author "Verified source author" \
  --output ../../datasets/recognition/private/promoted/<candidate>-sample.json
```

输出是可加入 `manifest.json.samples[]` 的 `EvaluationSample`，包含双人标注 provenance 以及由
首轮标注计时生成的 `correctionSessions`。工具不会自动修改 manifest 或提升 `datasetVersion`。
私有原图、工作包、标注、review 和未发布样本不得
因为导出而进入 Git。

## 运行评测

```bash
cd services/api
source .venv/bin/activate
python -m app.recognition_evaluation ../../datasets/recognition/manifest.json \
  --output ../../datasets/recognition/reports/opencv-baseline.json
```

完整 manifest 内容、识别管线和阈值相同时会生成相同 `reportId`；修改标注或修正记录也会改变
身份。图片缺失或 SHA-256 不一致进入 `invalid`；识别器失败进入 `recognition_failed`，并按
零预测计入召回率，二者都不会被静默排除。
