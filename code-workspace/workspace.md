# code workspace

## Workspace Manifest

`/Users/fujie/.dotfiles/code-workspace` is the Git-managed source. `/Users/fujie/code`
is the installed runtime view. `workspace.md` is the human guide; machine-readable paths,
default locations, commands, and rule values live in `/Users/fujie/code/workspace.toml`.
Update that manifest first, then update prose docs and generated files.

## Purpose

This workspace supports Japanese stock analysis, portfolio management, automation skills, and agent workflow experiments.

Codex and Claude Code are both expected to operate here. Shared rules live in this file. Tool-specific entrypoints should stay thin.

## Primary Areas

| Path | Purpose |
|------|---------|
| `/Users/fujie/code/repo/stock-analysis` | Stock analysis research module, CLI, and backtesting. Independent git repository. |
| `/Users/fujie/code/repo/nikkei-research-os` | Frozen R001-R006 overnight-research evidence and prospective-study maintenance. No new strategy research. |
| `/Users/fujie/code/repo/nikkei225-factor-lab` | Primary active repository for factor research, portfolio simulation, paper trading, and strategy operations. |
| `/Users/fujie/code/repo/` | Root for independent project git repositories. Each project owns its repository boundary. |
| `/Users/fujie/code/repo/playground` | Playground/scratch git repo for experiments and temporary work. |
| `/Users/fujie/code/repo/tradingagents` | TradingAgents implementation and tests. Independent git repository. |
| `/Users/fujie/.dotfiles/portfolio-core` | Shared SBI portfolio auth/fetch implementation used by Claude and agent wrappers. |
| `/Users/fujie/.dotfiles/claude/skills` | Git-managed Claude skill definitions. |
| `/Users/fujie/.agents/skills` | Agent runtime skill mirror. Should not be treated as the source of truth. |
| `/Users/fujie/code/ai` | Workspace-local source definitions for dual Codex/Claude agents. |
| `/Users/fujie/code/docs` | Plans, lessons, and reviews. |
| `/Users/fujie/code/repo/claude-code-best-practice` | External reference material for Claude Code/Codex workflows. Independent git repository. |
| `/Users/fujie/code/runtime` | Generated state and run outputs that are not source code. |
| `/Users/fujie/code/scratch` | Temporary experiments. |

## Shared Rules

- 使用中文回复用户。
- 计划、进度更新、审查意见、技术说明、代码相关信息和面向用户的标签均使用中文。
- 代码注释在确有助于理解时使用中文，避免添加显而易见的注释。
- 在语言、运行时和工具链支持的情况下，新增或修改的内部源码标识使用中文。外部定义或
  已冻结的 API 名称、协议与 Schema 键、枚举与状态值、CLI 参数、文件路径、第三方名称
  及兼容性敏感标识必须保持其规定形式。不得为统一语言而批量重命名无关的既存标识。
- 提交语言等机器可判定的规则值以 `workspace.toml` 的 `[rules]` 为唯一事实来源；旧计划或任务文档中的复制值不具权威性。
- Security-sensitive files, credentials, brokerage Cookies, and personal portfolio data must not be committed.
- For non-trivial work, write or update a plan before implementation.
- Default Codex/Claude split for implementation work: Codex owns design, planning, review, and verification; implementation edits should be delegated to Claude Code unless the user explicitly asks Codex to edit directly or the change is a small urgent fix.
- Prefer one source of truth and generated tool-specific files over duplicated manual definitions.
- Do not move files across git repository boundaries without checking `git status` and recording the rollback path.
- Generated daily analysis outputs belong under `runtime/` or ignored result directories, not mixed with source unless explicitly curated as fixtures.
- 新任务状态、持久化计划和归档分别使用 manifest 声明的默认目录；旧 `tasks/` 仅作历史内容，不再作为入口。
- 非平凡任务使用 `templates/task.md` 和 `scripts/taskctl`。完成状态由当前风险、preflight 与绑定当前 Git/工作树指纹的证据重新推导，不接受任务 Markdown 中手写的完成声明。
- 任务 Markdown 是可编辑定义；repository Git metadata 内的 task registry、任务旁的 sidecar 与 evidence JSON 由程序管理，不手工编辑。登记键由 repository identity 与 task ID 共同决定，不依赖可切换的 workspace root；已登记任务移动定义或缺少 sidecar 时拒绝重新初始化。任务定义、branch、HEAD、staged/unstaged diff、相关 untracked 文件或验收命令变化后，旧证据失效；重新执行并通过当前验收后可恢复关闭流程。
- 该机制处于本地信任边界：它防止手写完成、复用失效证据和跳过结构化强制门，但不声称具有密码学签名、远程身份认证或不可变存储保证。
- Claude Code automatically loads `~/.claude/CLAUDE.md` for user-level rules. This workspace file covers project-level rules only.
