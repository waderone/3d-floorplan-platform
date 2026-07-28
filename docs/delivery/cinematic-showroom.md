# 暖木极简客厅离线商业效果展厅

## 交付内容

首个商业效果基准使用已复核真实户型的客厅结构，不虚构窗户。最终包包含：

- 3840 × 2160、384 采样、16 位 PNG 主效果图；
- 8192 × 4096、256 采样、16 位 PNG 交互全景；
- 面向浏览器的高质量 JPEG；
- 无外部网络依赖的中文展厅；
- 可监听局域网的 macOS 原生启动器；
- 场景规格、渲染报告、资产清单、许可证和逐文件 SHA-256 清单。

交付基准采用 Blender Cycles、Metal、AgX 色彩管理、降噪和自适应采样。家具与
PBR 素材来自冻结并校验的 Poly Haven CC0 资源，定制沙发、空间结构、楼梯焦点
和墙面艺术由项目脚本生成。

## 客户操作

1. 解压 `warm-minimal-living.zip`。
2. macOS 双击 `启动展厅.command`；首次出现安全提示时选择允许。
3. 电脑浏览器会自动打开 4K 主图，点击右上角“8K 全景”可拖动查看。
4. 手机或平板连接电脑所在的同一 Wi-Fi。
5. 在移动设备浏览器输入启动窗口打印的 `http://局域网地址:端口/`。
6. 展示结束后关闭启动窗口，或在窗口中按 `Control + C`。

交付包完全离线运行；局域网访问只在现场电脑与同一 Wi-Fi 的设备之间传输。

## 重建

```bash
python3 tools/cinematic/prepare_assets.py

/Applications/Blender.app/Contents/MacOS/Blender \
  --background --factory-startup \
  --python tools/cinematic/build_warm_living.py -- --profile hero

/Applications/Blender.app/Contents/MacOS/Blender \
  --background --factory-startup \
  --python tools/cinematic/build_warm_living.py -- --profile panorama

python3 tools/cinematic/package_showroom.py
```

默认目录包位于 `work/deliveries/warm-minimal-living`，ZIP 位于
`work/deliveries/warm-minimal-living.zip`。`work` 是大型派生文件目录，不进入
普通 Git；源码、资产冻结清单、许可证和重建工具进入版本控制。

## 当前边界

- 本次冻结的是“真实户型暖木极简客厅”这一房间与风格的最终画质基准，不声称
  其余房间和风格已经达到同等级。
- 交付物以高质量主图和可查看全景为核心，不包含自由行走的实时 3D 网格。
- 启动器当前面向 macOS；其他系统可用任意静态文件服务器打开同一目录。
