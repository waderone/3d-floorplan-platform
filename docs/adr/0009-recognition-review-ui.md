# ADR-0009：识别建议人工复核与场景写入

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

把 `review_required` 户型识别 manifest 接入 Pascal 产品编辑器，建立“识别建议可见、
逐项人工决策、只写入已接受项、继续原生编辑、按 revision 保存”的完整闭环，同时确保
过期结果、错项目结果和重复应用不会污染权威场景。

## 决定

1. 复核功能位于 Pascal `apps/editor` 产品宿主层，不进入 `packages/core` 或
   `packages/viewer`。识别是平台工作流，不是通用场景节点或 3D 渲染能力。
2. 用户必须先上传底图、完成 Guide 比例标定并保存场景。前端用当前 Level 的已标定 Guide
   提取 asset id 和参考宽度，再以当前 scene revision 创建识别任务。
3. 前端严格解析 manifest，并同时校验 project id、scene revision 和 asset id。任务轮询期间
   如果场景被其他操作保存为新 revision，旧结果仍可查看，但禁止应用并要求重新识别。
4. 面板展示服务端生成的墙/房间叠加图、整体与单项置信度，并为每条建议维护
   `pending/accepted/rejected` 三态。未决和拒绝项永远不进入场景。
5. 识别坐标不会直接当作 Level 坐标。转换同时消费 image size、plan pixel bounds、
   pixels-per-meter，以及 Guide 的宽高、位置和 Y 轴旋转；墙厚与房间面积也按同一像素映射
   换算为场景米制，因此底图四周留白不会造成整体平移或比例偏差。
6. 已接受墙体转换为 Pascal Wall，房间转换为 Zone，并写入当前 Level。metadata 保留
   recognition id、suggestion id、asset id、pipeline version、来源 revision 与置信度，供审计。
7. 节点 id 由 recognition/suggestion 稳定派生；创建前还会按 asset、pipeline、suggestion
   检查已应用节点。因此同一任务重复点击，或同一底图在新 revision 上重新识别，都不会覆盖
   用户已修改节点或复制已存在建议。
8. 应用只调用当前编辑态的批量 `createNodes`，不直接 PUT API。后续继续复用 Pascal 自动保存
   与 FastAPI `expectedRevision` 冲突控制；用户可立即用原生 2D/3D 工具继续修正墙体和 Zone。

## 真实验证

- 在独立项目 revision 1 上真实触发 OpenCV 识别，面板收到 5 条墙体和 2 个房间建议，叠加图
  在桌面端完整显示；映射后的外墙长度约 9.97 m，与已标定底图约 10 m 主体宽度一致。
- 人工拒绝第 1 条墙、接受其余 6 条后，场景自动保存为 revision 2；服务端场景包含 4 个
  recognition Wall、2 个 recognition Zone，共 10 个节点，metadata 与父级关系均正确。
- 识别期间另一次人工建墙令 revision 从 2 前进到 3，旧识别结果被明确阻止应用，验证了并发
  编辑不会被静默覆盖。
- 基于 revision 2 重新识别后只接受已存在的第 2 条墙，界面提示未重复创建，场景仍为
  revision 2，节点数保持不变。
- 390×844 手机视口下，复核面板宽 366 px、`scrollWidth === clientWidth === 364`，叠加图、
  三态按钮、滚动列表和底部应用按钮均可用。
- 纯逻辑测试覆盖严格解析、失败载荷、revision/asset 错配、接受/拒绝过滤、像素到 Guide
  映射、墙厚/房间面积和跨任务幂等；Biome、editor TypeScript 检查全部通过。

## 已知限制与下一步

- 当前面板只做接受、拒绝和批量应用；精确端点、墙厚、房间名称/类型修正复用 Pascal 原生
  编辑工具，尚未提供在建议态内直接修改数值的表格。
- suggestion id 的跨任务幂等依赖同一 asset 与 pipeline version。算法版本升级后必须显式设计
  旧建议替换/合并策略，不能静默覆盖。
- 当前 OpenCV 基线仍不识别门窗、房型语义、斜墙和复杂图纸。下一阶段应先建立合法真实评测集，
  再升级模型和量化人工修正时间。
