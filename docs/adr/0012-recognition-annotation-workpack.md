# ADR-0012：候选审核与标注工作包

## 背景

ADR-0011 已建立只读候选队列，但候选与 ADR-0010 的正式评测 manifest 之间仍缺少可审计作业层。
图面筛选、权利批准和几何真值是不同责任：把“看起来是户型图”当成“已确认可商用”，或把当前
识别结果当成真值，都会直接污染后续准确率。

## 决策

1. 新增 `CandidateReviewFile`，把 curation 与 rights 分开。curation 记录图面类型、目标域、选择
   决定、原因、已知宽度、尺度证据、审核人和日期；rights 单独记录 pending/approved/rejected、
   商业使用、再分发、依据、审核人和日期。
2. selected 候选必须是单纯 floor plan，并具有 `planWidthMeters` 和非空尺度证据；立面、剖面、
   混合工程页和其他图面只能拒绝。被筛选拒绝或权利拒绝的候选不能生成标注工作包。
3. rights 为 pending 时，商业使用和再分发确认必须均为 false，且不能预填依据或签署人；approved
   必须显式确认商业使用并具有依据、审核人和日期。图面筛选可以由工具辅助，权利决定不能由
   Commons 提供方标签自动生成。
4. 工作包重新核验本地图片文件名、SHA-256、字节数和解码尺寸，然后运行版本化 OpenCV 基线。
   墙、房间、门窗和叠加图全部位于 `suggestions`，并固定 `isGroundTruth: false`。
5. 独立 `groundTruth` 初始为空且 `annotationStatus: pending`。本工具固定输出
   `promotionEligible: false`；权利未批准时列出 `rights_review_pending`，真值未完成时始终列出
   `ground_truth_pending`。正式晋级只能由后续人工标注、复核流程完成。
6. `workpackId` 由候选 id、图片 SHA-256、完整审核记录和识别管线版本确定；同一审核输入可稳定
   定位，修改尺度、决定、权利状态或管线版本会改变身份。

## 验收

- 自动测试覆盖选择/权利状态分离、已批准权利的必填字段、文档示例、预测与真值隔离、拒绝样本
  阻止、原图 SHA-256 错误和工作包阻断原因。
- 真实 `commons-190205778` 工作包校验 98,336 字节原图并生成 525,208 字节叠加图；基线仍为
  40 墙、1 房间、0 洞口，ground truth 为 0/0/0。
- 实际输出 `promotionEligible=false`，同时列出 `rights_review_pending` 和
  `ground_truth_pending`；外部图片、工作包 JSON 和叠加图均保持在 Git 忽略目录。

## 已知限制与下一步

- 工作包不是标注编辑器，当前仍需在图面上人工合并墙体、绘制房间内边界、标记门窗和复核尺度。
- 现有 20 张 Commons 候选只有一张较接近现代住宅，无法达到 20～50 张目标域要求；仍需用户
  自有、委托或明确授权的现代中文户型。
- 下一小阶段应实现人工真值编辑/导出和双人复核，再由独立晋级器生成 ADR-0010 manifest；在此
  之前不应开始用这些候选声称算法准确率。
