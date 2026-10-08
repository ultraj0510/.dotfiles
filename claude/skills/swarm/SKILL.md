---
name: swarm
description: "把实施任务交给固定 Haiku worker，主 Agent 负责协调和验收。只在用户显式调用 /swarm 时使用。"
disable-model-invocation: true
---

# Swarm

只在用户显式调用 `/swarm` 后使用。派发任何任务前，读取 `~/.dotfiles/agent-guidance/swarm.md`，并将 `~` 解析为用户主目录。若文件缺失或无法读取，停止委派并报告阻塞。只派给当前会话中已注册的 `worker`，并确认模型为 `claude-haiku-5-5`。角色不可用或模型不可用时，暂停委派并报告，不使用其他模型。遵循该共通规则。
