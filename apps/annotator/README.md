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
4. 首次真值编辑后自动累计有效时间；页面失焦、隐藏或连续 30 秒无操作时暂停。随时导出 `draft`
   草稿可保留累计值，重新载入后继续。
5. 完成后填写标注人，导出 `ready-for-review` 文件交给第二人复核。
6. 在 API 目录用后端契约再次校验导出文件：

```bash
cd services/api
python -m app.recognition_annotation_submission \
  --workpack ../../datasets/recognition/private/annotation-workpacks/<candidate>/workpack.json \
  --annotation /path/to/<candidate>-ready-for-review.json
```

新导出的 `ready-for-review` 必须包含当前识别算法版本和大于零的有效编辑时间。工具只保存累计秒数，
不保存鼠标轨迹、按键内容或页面焦点历史。该状态只表示几何已由标注人交接，不代表权利审核完成，
也不会自动晋级为正式评测 manifest。原图、工作包、草稿和导出结果应继续保存在已忽略的私有目录。

## 第二人复核

复核员重新载入同一工作包、原图和标注员导出的 `ready-for-review` JSON。右侧
`SECOND REVIEW` 会显示原标注人和文件 SHA-256 摘要：

- 选择“退回修改”时必须填写具体原因；
- 选择“批准复核”时复核人必须与标注人不同；
- 导出的 review JSON 绑定原标注文件的完整 SHA-256，标注内容发生任何变化后旧 review 都会失效。

复核可以与权利审核并行进行，但只有几何复核通过且 rights 为 `approved` 时才能晋级正式评测样本。
晋级命令及目录边界见 `datasets/recognition/README.md`。

## 验证

```bash
npm test
npm run build
```
