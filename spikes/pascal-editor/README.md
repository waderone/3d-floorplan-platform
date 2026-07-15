# Pascal Editor Spike

用于验证 Pascal Editor 是否适合作为 3D 户型编辑器底座。

## 固定版本

- 产品化镜像：https://github.com/pascalorg/editor
- 原始上游：https://github.com/pascalorg/editor
- Commit：`87975e297620457e1d86cbdf2d02fae93119c0f0`
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

Phase 0 的固定 commit 未修改上游代码。PoC 在私人镜像的独立分支做窄幅产品化
接入，主仓库仍通过 submodule commit 精确固定版本。验证结果、运行命令和已知
缺口记录在 ADR-0001、ADR-0002 和项目进度中。
