# Claude Code 工作区入口

面向人的共享指南见 `/Users/fujie/code/workspace.md`，机器可判定的结构、路径、默认值、命令和规则值见
`/Users/fujie/code/workspace.toml`。系统概览见 `/Users/fujie/code/README.md`。

## Claude 专属说明

- 使用 `/Users/fujie/code/workspace.md` 理解共享行为指南和职责边界。
- 以 `/Users/fujie/code/workspace.toml` 作为机器可读工作区事实的权威来源。
- `.claude/` 仅用于 Claude 专属的代理、规则、钩子和本地设置。
- 除非 Claude 需要不同的行为，否则不要在此处重复 Codex 专属的指令。
- 非平凡任务从 `templates/task.md` 创建定义，并运行 `scripts/taskctl start <task-file>`。
- 不手写 `COMPLETE`；使用 `scripts/taskctl close <task-file> --evidence <evidence-file>` 重新推导结论。

## 股票分析系统

独立项目位于 `~/code/repo/stock-analysis/`。技能通过 symlink（`~/.dotfiles/claude/skills/stock-*` → `~/code/repo/stock-analysis/skills/stock-*`）提供。

### 每日工作流（`stock-advisor`）

1. 用户运行 `/portfolio-auth` 确保 SBI cookie 有效
2. 用户运行 `/portfolio-fetch` 刷新投资组合数据
3. 用户运行 `/stock-advisor`，其内部：
   - 调用 `run_daily_actions.py` → 每个股票代码子进程执行 `stock-company-analyze`
   - `stock-company-analyze` 运行其 7 阶段管道 → 每个股票代码生成 `analysis.json`
   - `portfolio_helper.py` 叠加投资组合约束（保证金、信用期限、集中度）
   - 输出 `daily_actions.json` 和 `report.md`

### 深度分析（`stock-company-analyze`）

独立的单股票分析。使用 `/stock-company-analyze <股票代码>`。
生成 `analysis.json` v2.0，包含技术面、基本面、综合面和预测模块。

### 关键约束

- stock-advisor 只关注投资组合/观察列表/账户/报告——绝不重新计算技术指标或预测
- stock-company-analyze 只关注证据/技术面/基本面/预测——绝不读取投资组合
- 所有 schema 变更都是增量式的（v2.0 新增模块，v1.0 消费者不受影响）
- 测试：stock-advisor 220 个测试，stock-company-analyze 88 个测试——提交前运行

### 技能调用规则

- 使用 `Skill` 工具调用技能——不要手动读取 SKILL.md
- stock-advisor 要求先运行 `portfolio-fetch`
- stock-company-analyze 也可以作为子进程从 `run_daily_actions.py` 调用
