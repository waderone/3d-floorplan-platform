# Pascal Editor Spike

用于验证 Pascal Editor 是否适合作为 3D 户型编辑器底座。

## 固定版本

- 上游：https://github.com/pascalorg/editor
- Commit：`a59074774898116c0e7116b424b371e5e3420ea4`
- 许可证：MIT，详见 `upstream/LICENSE`

## 初始化

```bash
git submodule update --init --depth 1
```

## 验证

在 `upstream` 目录执行：

```bash
bun install --frozen-lockfile
bun check-types
bun run build
```

`bun` 需要位于当前 `PATH`，否则 Turborepo 子进程无法定位包管理器。

本 spike 不修改上游代码。验证结果、运行命令和已知测试缺口记录在 ADR-0001 和项目进度中。
