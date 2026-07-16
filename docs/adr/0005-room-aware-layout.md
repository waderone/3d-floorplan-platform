# ADR-0005：房间感知布局与三风格技术闸门

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

把上一阶段固定在模型中心的程序化陈设升级为房间感知布局，并证明同一份确定性 layout
manifest 可以驱动 Babylon.js Viewer 与 Blender Worker；同时把风格目录扩展到三套产品预设。

## 决定

1. 权威房间语义优先来自 Pascal SceneGraph 的 `zone.polygon`；没有 Zone 时才读取
   `slab.polygon`。site 启动边界和未闭合墙线不被伪装成房间。
2. 风格包升级为 Schema 1.1。primitive 増加 `itemId` 和 `collisionMode`，layout 配置增加
   `wallClearance` 与 `itemClearance`。多个 primitive 可以组成一件家具，地毯等 surface
   允许与实体重叠。
3. API 的 `room-aware-layout-v1` pipeline 按面积和稳定 id 排序候选房间，选择首个能容纳
   模板的房间，检查家具包围盒到墙边界以及家具之间的净距。算法不缩放家具，以免掩盖
   房间过小。
4. layout manifest 包含 project、scene revision、style id/version、候选房间、选定房间、
   绝对坐标 placements 和内容哈希 `layoutId`。无有效房间或无房间可容纳时返回明确
   fallback，不生成虚假家具。
5. Viewer 与 Blender 都只消费最终 layout placements。RenderStore 把 layout JSON 固化到
   render 目录，render identity 包含 layoutId；两条渲染链不得在模型中心各算一套位置。
6. 风格目录提供 `warm-minimal@2`、`modern-contrast@1`、`nordic-light@1`。本阶段继续使用
   `LicenseRef-Project-Authored` 程序化资产，暂不导入许可证未审计的外部模型。

## API 契约

- `GET /api/projects/{projectId}/layout?styleId=warm-minimal`
- `POST /api/projects/{projectId}/renders`

layout 的 ready 状态包含 `selectedRoomId` 和 placements；fallback 状态的 placements 必须为空，
原因只能是 `no-room-polygon` 或 `no-room-fits`。render manifest 增加 `layoutId`，pipeline
版本升级为 `blender-5x-style-layout-v2`。

## 验证结果

- FastAPI 自动测试增至 46 项并全部通过，覆盖 Zone 优先、Slab 回退、确定性、revision
  identity、房间不足回退、三风格目录、layout API 和 Blender layout 传递。
- 三套风格在双房间 fixture 上均选择 56 m² 的客餐厅并输出 ready；家具分组通过 0.35 m
  墙距和 0.2 m 物件净距规则。
- Blender 5.2.0 LTS 真实消费 API 固化的 layout，三张 1280×720 EEVEE PNG 全部 ready，
  输出约 0.83–0.85 MiB；最终视觉检查确认三套色板、家具比例、墙距和房间聚焦正确。
- Viewer TypeScript 与 Vite 生产构建通过。桌面端三套 style 参数均 ready；390×844 手机端
  无滚动溢出或控制台错误，布局状态、3D/俯视/复位交互均通过。

## 已知限制

- v1 只在最大的可容纳房间放置一组客厅家具，还没有按客厅、卧室、餐厅等房间类型分别
  生成整屋方案。
- 当前碰撞使用确定性的二维包围盒和净距规则，适合轴对齐程序化模板；任意旋转、多边形
  家具、门窗开启区和通道宽度需要后续精确几何规则。
- 程序化家具仍是技术/产品预设，不是照片级商业资产。下一阶段需要许可证可审计的真实
  GLB/PBR 目录、LOD 和按设备预算选择资产。
- BackgroundTasks 仍无进程恢复、分布式锁和重试保证，生产部署必须迁移到独立任务队列。
