# Pascal Editor Spike

用于验证 Pascal Editor 是否适合作为 3D 户型编辑器底座。

## 固定版本

- 公开上游：https://github.com/pascalorg/editor
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

Phase 0 的固定 commit 未修改上游代码，主仓库通过公开 submodule commit 精确固定版本。
历史产品化集成结果记录在 ADR 中，但相关私有补丁不作为当前公开基线的一部分。新的编辑器
集成应通过可审查的公开 Issue 和 Pull Request 进入本仓库。
