# Render Worker

消费已发布的优化 GLB 与版本化装修风格包，通过 Blender 5.x 无界面模式生成 PNG 效果图。GLB 是权威场景的派生产物，风格包是独立表现层；Worker 不写回场景 JSON。

本地技术闸门：

```bash
blender --background --factory-startup --disable-autoexec \
  --python-exit-code 1 --python render_scene.py -- \
  --input /path/model.glb \
  --style ../../packages/style-schema/styles/warm-minimal-v1.json \
  --output /tmp/floorplan.png \
  --report /tmp/floorplan-report.json
```

API 通过 `FLOORPLAN_BLENDER_BIN` 指定 Blender 可执行文件。当前本机验收版本为 Blender 5.2.0 LTS；生产环境应使用固定 Blender 5.x 镜像和独立任务队列。

首套家具和材质全部是本项目原创程序化资产，不读取 `.blend`，并使用 `--disable-autoexec` 禁止不可信文件自动执行脚本。
