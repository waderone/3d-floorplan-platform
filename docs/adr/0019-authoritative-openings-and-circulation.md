# ADR-0019：权威门窗开口与动线净空布局

## 状态

已接受，2026-07-21。

## 背景

layout v2 只使用 Zone/Slab 房间多边形、墙边距和家具互碰规则。它不会读取 Pascal 场景中
挂在 Wall 下的 Door/Window，因此家具可能挡住门扇开启区或窗边接近区。上一资产切片使用的
哥特床也与现代、北欧和暖木三套产品风格不匹配。

## 决策

1. layout 升级为 schema `3.0`、pipeline `multiroom-opening-clearance-layout-v3`。只有权威
   场景中的 Door/Window 节点会生成 opening；识别建议仍须先经人工确认进入场景。
2. 直墙开口按 Pascal wall-local 坐标转换到楼层 X/Z。manifest 保存 source/opening/operation
   类型、宿主墙/楼层/房间、中心、宽高、窗台高度和世界坐标净空多边形。曲墙、孤儿节点和
   越界开口不猜测，进入 `ignoredOpeningIds`。
3. 铰链、双开、法式和折叠门保留至少门宽的双侧开启区；推拉/洞口、车库门和窗保留确定性
   接近区。双侧是当前无法从房间内外语义可靠判定时的保守安全选择。
4. 布局从房间中心开始，以 0.25 m 网格、最多 4096 个候选按离中心距离搜索。候选必须同时
   通过房间边界/墙净空、家具间净空和所有关联 opening 净空；全部被开口阻断时列入
   `openingBlockedRoomIds`，不发布碰撞家具。
5. Viewer 严格拒绝 legacy v2，显示开口数量和阻断状态，并提供默认关闭的门窗动线虚线层。
   Blender Worker 同样只接受 v3，并把 opening/ignored/blocked/validated 指标写回渲染 manifest。
6. 资产目录升级为 v3。用可复现 Blender 脚本生成的项目原创现代软包床替换哥特床，生成器
   和 GLB 分别固定 SHA-256，5 个 PBR 材质使用 `preserve`，资产明确按 CC0 发布。旧哥特 GLB
   和导入项移除。

后续 `multiroom-opening-clearance-layout-v4` 保持 schema `3.0` 和以上开口契约不变，仅新增
紧凑卧室核心陈设回退，并对带双人复核 provenance 的小面积真实 Zone 放宽自动候选噪声阈值。

## 验收结果

- FastAPI 97 项、Viewer 8 项、严格 TypeScript/Vite 构建通过。
- 真实 4 m 卧室为 ready：11 个 placement、2 个权威 opening、0 blocked，唯一模型资源
  3,252,748 B。
- 1280×720 桌面和 390×844 手机真实浏览通过；手机无页面溢出，控制台无 warning/error。
- Blender 5.2 EEVEE preview 为 1.319 s、6 个真实模型、0 回退，并报告 2 个 opening、0 ignored/
  blocked、净空已验证。

## 明确不包含

- 曲墙/屋面墙开口的精确世界坐标。
- 依据门扇内外方向裁剪成单侧扇形净空。
- 任意旋转、全局最优或生成式家具求解器。
- 家具拖拽、约束反馈、布局保存和版本恢复；这些进入阶段 66e。
- KTX2、LOD、实例化和低端真机 5 秒/30 FPS 承诺；这些仍属于阶段 67。
