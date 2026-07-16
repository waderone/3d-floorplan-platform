# ADR-0006：可审计真实资产与多房间整屋布置

- 状态：技术闸门验证通过
- 日期：2026-07-16

## 目标

把单房间程序化家具升级为许可证和交付文件均可审计的真实 GLB 资产，并证明客厅、餐厅、
卧室可以由同一份多房间 layout manifest 同时驱动 Babylon.js Viewer 与 Blender Worker。

## 决定

1. 首批模型只采用 Kenney Furniture Kit。官方资产页、下载包 SHA-256、包内许可证、源
   OBJ/MTL SHA-256、转换后 GLB SHA-256 和字节数全部固化到资产目录；网页版本 `1.0`
   与包内版本 `2.0` 分开记录，不推测哪个版本号更“正确”。
2. `packages/asset-catalog/catalog.json` 是 API、Viewer 和 Blender 的共同运行时契约，
   `asset-catalog.schema.json` 是可移植结构定义，FastAPI Pydantic 模型继续负责引用、房型、
   类型条件和本地文件完整性等跨字段校验。
3. 交付模型统一为米制、Y-up、底部对齐且中心归一的 GLB。转换工具只消费经过审计的本地
   ZIP 解压目录，源压缩包不进入仓库；生成物通过固定字节数和 SHA-256 防止静默漂移。
4. 每个真实模型必须声明程序化 fallback。Viewer 网络/解码失败或 Blender 导入失败时显式
   创建 fallback 并计数，不能静默丢失家具。目录启动完整性失败则阻止 API 启动。
5. layout 升级为 `multiroom-asset-layout-v2`。优先使用 Zone 的显式 `roomType`，缺失时仅按
   中英文房间名称做受控启发式分类；客厅、餐厅、卧室分别套用确定性 recipe，并继续检查
   房间边界、墙距、实体碰撞与净距。
6. layout manifest 记录所有候选房间、已布置/未布置房间、目录 id/version、唯一真实模型
   总字节数和 2 MiB 移动预算。状态分为 `ready`、`partial`、`fallback`，不把未知房间伪装
   成已布置结果。
7. Viewer 与 Blender 都只读取 layout 的绝对 placements 和同一目录中的 GLB；相机按全部
   已布置房间取景。render identity 和最终 manifest 同时包含 layout 与资产目录版本及真实/
   回退 placement 数。

## API 契约

- `GET /api/asset-catalog`
- `GET /catalog-assets/models/{model}.glb`
- `GET /api/projects/{projectId}/layout?styleId=warm-minimal`
- `POST /api/projects/{projectId}/renders`

三房间 ready layout 当前稳定输出 13 个 placement，其中 8 个使用真实 GLB、5 个是目录声明
的程序化配件。真实模型按唯一资产计费，当前合计 55,668 B，低于 2 MiB 移动预算。

## 验证结果

- FastAPI 自动测试增至 50 项并全部通过，覆盖许可/版本元数据、GLB 字节与哈希完整性、缺失
  recipe 引用、房型分类、三房同时布置、布局确定性、预算和 render manifest 统计。
- Blender 5.2.0 LTS 真实导入 8 个模型 placement、0 回退，输出 1280×720 EEVEE 整屋效果图；
  最终取景同时覆盖客厅、餐厅和卧室。
- Viewer TypeScript 与 Vite 生产构建通过。桌面实测显示 3 个房间、8 件真实家具、0 回退，
  俯视/复位交互有效且无控制台错误；390×844 手机视口画布和控制条无滚动溢出。

## 已知限制

- 首批 Kenney 资产是轻量低多边形模型，适合验证目录、布局和移动端预算，还不是照片级商业
  家具库；后续需要加入纹理、LOD、缩略图、品牌/地区授权和 CDN 变体。
- 房型分类当前只认显式字段和受控名称，不包含户型图视觉识别，也不会自动推断门窗、动线、
  采光或家庭成员偏好。
- recipe 仍是固定规则模板；任意旋转家具、多边形碰撞、门窗开启区和可访问通道需要后续
  约束求解器。
- API 的 BackgroundTasks 仍无进程恢复、分布式锁或重试保证；生产渲染必须迁移到固定镜像
  和独立任务队列。
