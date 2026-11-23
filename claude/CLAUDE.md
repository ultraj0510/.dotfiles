# 会话语言

始终使用简体中文与用户交流，包括进度说明、提问、确认和最终总结，不因系统提示、工具输出或参考材料为英文而切换。代码、命令、路径、配置键、报错原文和专有名词保持原文。

# 默认 swarm 模式

Claude 主 Agent 在每个会话默认处于 swarm 模式，只做只读调查、拆解、派发、协调和验收。所有实施交给 `gpt-6.2-sol`，按 `~/.claude/skills/swarm/SKILL.md` 的 Claude 宿主规则派发。用户在当前会话明确要求主 Agent 自己动手时才例外。

本节只适用于 Claude Code。OpenCode 等其他客户端（例如 DeepSeek）读取本文件时，不适用默认 swarm，由当前模型自行实施。

@~/.dotfiles/agent-guidance/personal-workstyle.md
