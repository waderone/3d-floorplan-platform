# 户型真值标注台

面向离线评测集制作的轻量 Web 工具。它读取 ADR-0012 工作包和对应原图，在浏览器内编辑墙体、
房间、门窗及房型语义，并导出独立的标注提交文件。机器识别建议只作为橙色参考层，只有人工明确
复制或绘制的几何才进入真值。

## 本地运行

需要 Node 22.12 或更高版本：

```bash
cd apps/annotator
npm install
npm run dev
```

打开终端输出的本地地址，依次选择 `workpack.json` 和工作包声明的原图。工具会在允许编辑前核验
图片 SHA-256 与像素尺寸。访问 `http://127.0.0.1:4174/?demo=1` 可载入不含外部数据的内置演示。

## 标注流程

1. 载入工作包和原图，确认候选、尺度、图片完整性与权利状态。
2. 保持机器建议为只读参考；需要复用时显式复制，再逐项修正。
3. 使用墙体、房间、门、窗工具绘制几何；选择真值后可拖动控制点或编辑数值/房型。
4. 随时导出 `draft` 草稿；完成后填写标注人，导出 `ready-for-review` 文件交给第二人复核。
5. 在 API 目录用后端契约再次校验导出文件：

```bash
cd services/api
python -m app.recognition_annotation_submission \
  --workpack ../../datasets/recognition/private/annotation-workpacks/<candidate>/workpack.json \
  --annotation /path/to/<candidate>-ready-for-review.json
```

`ready-for-review` 只表示几何已由标注人交接，不代表权利审核完成，也不会自动晋级为正式评测
manifest。原图、工作包、草稿和导出结果应继续保存在已忽略的私有目录。

## 验证

```bash
npm test
npm run build
```
