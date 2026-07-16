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
- 完成人工修正后，在 `correctionSessions` 记录所用识别管线、修正秒数、复核人和日期。

默认指标阈值为墙端点 0.25 米、房间 IoU 0.5、门窗中心 0.3 米、门窗宽度 0.2 米。
报告输出墙体、房间和门窗的 precision/recall/F1，以及墙端点平均误差、房间平均 IoU 和
房间语义准确率。首版主要产品目标仍是人工修正中位时间，而不是只追求单一像素指标。

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
