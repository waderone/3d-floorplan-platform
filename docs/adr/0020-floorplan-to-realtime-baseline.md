# ADR-0020：户型图到客户实时 3D 的主线基准

## 状态

已接受，2026-07-22。

## 背景

项目已经分别具备户型识别、人工复核、场景版本、GLB 优化、三风格布局、真实家具和多端
Viewer，但模块分别可用不等于用户目标已经成立。产品主方向必须以一条可重复验证的完整链路为
基准：上传户型图，自动得到客户可实时浏览、可切换装修风格的 3D 户型。

## 决策

1. Viewer 无 `project` 参数时显示单次上传入口。用户提供项目标识、户型外边界实际宽度和
   PNG/JPG；前端只调用一个 baseline POST，并按 manifest stage 轮询，ready 后跳转客户链接。
2. API 在一个显式任务中串联真实识别、结构建议自动接受、revision 2 权威 Wall/Zone 场景、
   确定性结构 GLB、现有 glTF-Transform 优化和全部三套风格 layout。任何一步失败都持久化
   `failed`，不返回部分成功的客户链接。
3. 自动接受仅作为直墙、闭合自由空间技术基准，所有接受项保留 recognition provenance 和
   `baseline-auto-accepted` decision。门窗、曲墙、文字干扰和可靠房间语义继续明确记录为限制，
   通用生产流程仍需人工复核和真实评测集。
4. 场景、布局、GLB 和 Viewer 统一采用米制、右手坐标、Y-up、XZ 地面。Viewer 显式启用
   Babylon 右手 Scene；生成器输出自然 `+X/+Z`，不依赖 Loader 隐式根翻转。
5. 结构 GLB 可以由多个语义墙节点共享单位网格，但优化器禁止 `instance/flatten/join`，并比较
   优化前后的 `pascalId` 节点数。Viewer 显式加载 Babylon `InstancedMesh` 支持，以兼容共享
   mesh 的标准 glTF 节点。
6. 同一项目标识不可覆盖。当前使用 FastAPI `BackgroundTasks` 只作为本地技术基准；生产迁移到
   队列、对象存储和用户权限时保留 baseline manifest 与 viewer URL 契约。

## 验收结果

- API 100 项、Viewer 11 项、Model Worker 2 项测试通过；Viewer 严格 TypeScript 与 Vite 生产
  构建通过。
- 用 500×400 双房间直墙图真实上传，OpenCV 生成 5 段墙和 2 个房间，三套 layout 均 ready；
  客户 Viewer 显示 2 个空间、11 组家具、6 个真实模型。
- 1280×720 桌面截图确认外墙/隔墙、地板和两房家具对齐；暖木极简切换北欧浅色、卧室聚焦
  视角均完成真实点击验证。
- 390×844 手机上传页和 ready Viewer 无横向溢出；三风格与四个视角入口可达，并成功切换到
  现代深色，使用移动优化画质。

## 明确不包含

- 任意质量户型图的无人工成功率承诺。
- 门窗、曲墙、斜墙、文字 OCR 和可靠房间用途分类。
- 照片级实时材质、全量商业家具库或低端真机帧率承诺。
- 家具拖拽、约束反馈、布局保存恢复、账号权限和公开部署。
