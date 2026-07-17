# ADR-0014：双人复核与评测样本晋级

## 背景

ADR-0013 已能由标注员导出 `ready-for-review` 真值，但该状态仍是单人声明。若没有独立复核、内容
绑定和权利门槛，修改后的标注可能复用旧结论，同一个人也可能同时充当标注员和复核员，最终污染
识别准确率基线。

## 决策

1. 新增独立 `AnnotationReview`：记录工作包、候选、标注文件 SHA-256、`approved` 或
   `changes-requested`、复核人、日期和说明。退回必须填写说明；复核人与标注人按去空格、忽略
   大小写比较后必须不同。
2. review 绑定标注 JSON 的原始字节 SHA-256，而不只绑定 workpack。任何重排、修改甚至文件字节
   变化都会让旧 review 失效；复核员必须基于实际交接文件重新签署。
3. 几何复核与权利审核保持独立：rights pending 时允许先复核几何；promotion 同时读取原工作包和
   最新候选审核文件，只接受 curation 未变、`review=approved` 且最新 `rights=approved`、商业
   评测已确认的组合。权利签署无需重做几何标注，尺度或筛选结论变化则必须重新生成工作包。
4. 晋级器重新验证工作包/候选身份、几何标定边界、标注摘要、图片 SHA-256、存储模式和数据集
   相对路径，再生成 ADR-0010 `EvaluationSample`；不原地修改工作包、标注、review 或 manifest。
5. `EvaluationSample` 增加向后兼容的可选 `annotationProvenance`，记录 workpack、submission 摘要、
   标注员/日期和复核员/日期。旧 manifest 无需补字段，新晋级的 complete 样本必须由晋级器写入。
6. `repository` 样本必须位于 `images/` 且允许再分发；`local-only` 样本必须位于已忽略的
   `private/`。来源标题和作者由晋级命令显式提供，避免把候选标题中的联系方式直接复制到报告。

## 验收

- 后端测试覆盖退回必填说明、自审禁止、标注摘要篡改、双人 provenance、权利阻断、退回阻断和
  repository/private 目录边界；晋级结果能通过现有 `EvaluationSample` 契约。
- 标注台提供第二人复核区，载入待复核文件后显示原标注人和摘要，可导出批准或退回 review；前端
  单测覆盖自审与退回原因，严格 TypeScript 和生产构建通过。
- CLI 提供 `review` 与 `promote` 两个显式子命令。它们只写指定输出文件，不自动修改正式 manifest，
  避免多人同时晋级时静默覆盖数据集版本。

## 已知限制与下一步

- 当前是离线文件交接，没有账号鉴权、电子签名、任务锁、退回通知或在线审计日志；人员名称仍由
  团队流程保证真实。
- 晋级器生成单个 sample JSON，仍需人工评审后合并并提升 `datasetVersion`。后续生产化应在数据库
  事务中完成复核状态与数据集版本发布。
- 标注台尚未自动记录人工修正时长；收集首批真实样本时需要增加计时，阶段 61 才能计算修正中位数。
