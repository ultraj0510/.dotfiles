# 自定义 Skills 与 Agents

本目录维护共享个人规则、两个完整 Skill 和两个 Codex Agent。运行入口使用符号链接，日常修改直接编辑本目录的源码；不在运行目录维护第二份副本。

| 类型 | 源码 | 运行入口 |
|---|---|---|
| Skill | `skills/equity-opportunity/` | `~/.codex/skills/equity-opportunity` |
| Skill | `skills/sbi-research-data/` | `~/.codex/skills/sbi-research-data` |
| Agent | `agents/luna-worker.toml` | `~/.codex/agents/luna-worker.toml` |
| Agent | `agents/nikkei225-opportunity.toml` | `~/.codex/agents/nikkei225-opportunity.toml` |

Skills 包含 `SKILL.md`、`references/` 和 `agents/openai.yaml`。Agent 内引用的 `~/.codex/skills` 绝对路径保留现有本机配置；迁到不同用户主目录时需检查这些引用。

## 安装与恢复

仓库根目录 `install.sh` 已声明上述四个链接，沿用现有 `backup_and_link` 行为：正确链接跳过，普通文件或目录先备份，未知符号链接拒绝覆盖。完整安装脚本还会安装其他 dotfiles；只维护这些文件时无需运行整个脚本。

本次迁移前的原件与逐文件 SHA-256 清单保存在 `~/.dotfiles-backup/custom-skills-agents-<时间>/manifest.json`。回退时核对清单，移除仍指向本目录的四个运行链接，再将对应备份移回；若源码已更新，先保存后续修改。

## 其他维护边界

- `skill-overrides/` 继续保存五个技能的指令覆盖文件，不是完整安装包，具体见其 README。
- `jp-investment-cycle` 已由 `jp-quant-sandbox/.agents/skills/` 管理，保持项目归属。
- Matt Pocock 技能、系统技能及供应商插件不复制到本目录。
- 本次不修复 Claude 的旧入口，也不恢复已退役角色。
