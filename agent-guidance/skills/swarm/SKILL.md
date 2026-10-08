---
name: swarm
description: "把实施任务交给固定 Luna worker，主 Agent 负责协调和验收。只在用户显式调用 $swarm 时使用。"
---

# Swarm

只在用户显式调用 `$swarm` 后使用。派发任何任务前，读取 `~/.dotfiles/agent-guidance/swarm.md`，并将 `~` 解析为用户主目录。若文件缺失或无法读取，停止委派并报告阻塞。

优先使用具名 `luna_worker`，并依据当前工具元数据或角色配置确认模型为 `gpt-6-luna`。模型无法确认时将该角色视为不可用。具名角色不可用或启动失败时，若当前调度工具支持明确指定 `gpt-6-luna`，可按该模型继续，并在回报中说明实际入口。`gpt-6-luna` 不可用时暂停并等待用户决定，不使用其他模型。遵循共通规则。
