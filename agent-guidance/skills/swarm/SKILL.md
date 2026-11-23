---
name: swarm
description: "把实施交给固定模型 worker（Claude 侧为 gpt-6.2-sol，Codex 侧为 gpt-6-luna），主 Agent 负责协调和验收。用于显式调用 swarm、上级指定 swarm 的委派，或全局指令声明默认开启的会话。"
disable-model-invocation: true
---

# Swarm

派发任何任务前，读取 `~/.dotfiles/agent-guidance/swarm.md`，并将 `~` 解析为用户主目录。若文件缺失或无法读取，停止委派并报告阻塞。

## Claude 宿主

主 Agent（Opus）只做协调和验收，worker 固定使用 Codex 的 `gpt-6.2-sol`。在 T3 Code 中使用 `delegate_task`，将 `target.providerInstanceId` 设为 `codex`，将 `target.model` 设为 `gpt-6.2-sol`。在 T3 Code 之外，用本机 `codex exec --model gpt-6.2-sol` 派发。两种入口均不可用时，暂停并报告，不更换模型，也不回退到 Haiku 或 Claude 原生 Agent。

## Codex 宿主

优先使用具名 `luna_worker`，并依据当前工具元数据或角色配置确认模型为 `gpt-6-luna` 且满足指定的运行设置。具名角色不可用、设置不符或启动失败时，使用可以明确指定该模型和所需设置的调度入口，并在回报中说明实际入口。无法满足时报告具体限制。遵循共通规则。

## 其他宿主

OpenCode 等其他宿主（例如 DeepSeek）不默认开启 swarm，也没有固定 worker。用户在这些宿主中显式调用 swarm 时，报告该宿主没有定义固定 worker 并暂停，不自行选择模型。
