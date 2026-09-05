# 自定义 Skill 覆盖文件

这些文件保存 2026-09-06 审阅后的五个自定义 Skill 指令，不是完整独立安装包。

应用前应已有同名 Skill 及其 references、scripts、assets 等资源；将对应文件复制到 `~/.codex/skills/<名称>/`，保留未列出的资源。不要将本目录直接作为完整 Skill 安装源。现有 `install.sh` 不会自动安装这些覆盖文件。

`cyber-ppt/legacy-workflow.md` 保存此前完整协议，仅当用户明确选择旧版流程时加载。`using-simplify` 和 `simplify` 应一起更新。本目录不包含供应商插件缓存。

恢复或更新前检查目标文件的现有修改；不要覆盖后续工作。Skill 内相对资源链接以安装后的完整 Skill 目录为基准。
