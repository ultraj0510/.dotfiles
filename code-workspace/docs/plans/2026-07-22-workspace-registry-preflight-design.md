# 工作区项目台账与预检治理设计

## 目标

让 `workspace.toml` 成为 `/Users/fujie/code/repo` 下所有一级 Git 仓库的完整台账，并让 preflight 对治理入口缺失、未登记仓库及必要 remote 缺失采取 fail-closed 行为。

## 范围

- 保留现有 `[repos]` 的 `name = "path"` 合同，避免破坏 `--repo`、taskctl 和既有测试。
- 新增 `workspace.repository_root = "repo"`，限定仓库发现范围。
- 新增 `[managed_links]`，登记 `scripts/` 与 `templates/` 的运行视图链接和持久源路径。
- 新增 `[repository_metadata.<name>]`，为每个仓库记录 `kind`、`lifecycle` 和 `remote_policy`。
- 补登记仍在维护范围内但尚未入表的 `download-photos`、`cc-connect`。
- preflight 只扫描 `repository_root` 的一级目录；发现未登记 Git 根时阻断。
- 空 verification 数组表示工作区没有统一验收命令，不再产生无意义 WARN。

## 非目标

- 本阶段不创建或修改 GitHub 仓库、remote、branch protection、Actions 或 PR 模板。
- 不清理现有 worktree、分支、未跟踪文件或生成物。
- 不修改 taskctl 的状态 schema、worktree 身份或证据门禁；这些属于后续独立计划。
- 不改变各研究仓库的代码、策略、产物或当前状态。

## 方案比较

### 方案 A：把 `[repos]` 改成嵌套 table

路径和元数据放在同一 table 内，表面上紧凑，但会破坏当前所有把 `[repos]` 值当字符串的调用方，迁移范围过大。

### 方案 B：保留 `[repos]`，新增平行 metadata 与 managed-links 表

保持路径合同不变，通过严格 key-set 校验防止台账漂移。preflight 可以增量读取新字段，taskctl 的 `--repo` 行为不变。

### 方案 C：只把遗漏仓库补进 `[repos]`

改动最小，但仍无法发现下一个未登记仓库，也无法验证 `scripts/templates` 链接来源，不能解决根因。

采用方案 B。

## Manifest 合同

```toml
[workspace]
repository_root = "repo"

[managed_links]
scripts = { path = "scripts", source = "code-workspace/scripts" }
templates = { path = "templates", source = "code-workspace/templates" }

[repository_metadata.stock_analysis]
kind = "research"
lifecycle = "active"
remote_policy = "required"
```

约束：

- `[repos]`、`[verification]`、`[repository_metadata]` 的 key 集合必须完全一致。
- `kind` 是非空字符串；`lifecycle` 仅允许 `active|maintenance|reference|archived`。
- `remote_policy` 仅允许 `required|optional`。
- `managed_links.*` 必须且只能包含 `path` 与 `source`，二者为非空相对路径。
- 当前 JSON report schema 保持版本 1；新增字段属于向后兼容扩展，避免在 taskctl 升级前破坏严格 schema 检查。

## 仓库分类

| key | kind | lifecycle | remote_policy |
|---|---|---|---|
| `stock_analysis` | `research` | `active` | `required` |
| `nikkei_research_os` | `research_control_plane` | `active` | `required` |
| `nikkei225_factor_lab` | `research_execution_plane` | `active` | `required` |
| `download_photos` | `utility` | `active` | `required` |
| `playground` | `sandbox` | `maintenance` | `required` |
| `tradingagents` | `external_reference` | `reference` | `required` |
| `claude_code_best_practice` | `external_reference` | `reference` | `required` |
| `cc_connect` | `external_tool` | `reference` | `required` |

`required` 只要求至少存在一个 remote，不要求 remote 名为 `origin`；因此任意
已配置的 remote 都可以满足合同。已废弃且不再处于工作区维护范围的项目不进入
manifest，也不再接受 workspace 管理。

## Preflight 行为

### Managed links

对每个 `managed_links` 项验证：

1. `runtime_view / path` 的父目录解析后仍在 `runtime_view` 内；否则为
   `INVALID`。
2. `source_repository / source` 必须存在，且解析后仍在 `source_repository`
   内；否则为 `INVALID`。
3. target 存在、是符号链接，且其解析结果等于 source 的解析结果。

因此，target 父目录或 source 路径中的中间符号链接若逃逸各自的受限根目录，
即使最终路径存在也属于 `INVALID`；只有受限检查通过但 target 缺失时才属于
`MISSING`。

任一失败产生 `MANAGED_LINK_MISSING` 或 `MANAGED_LINK_INVALID`，严重度为 `BLOCKED`。

### 仓库发现

只对 `runtime_view / repository_root` 执行一级 `iterdir()`：

- 跳过非目录；候选路径解析后，其父目录必须仍是 `repository_root`；
- 对候选调用 `git rev-parse --show-toplevel`，并要求输出解析后恰等于候选路径，
  以确认候选自身就是 Git 根；
- Git 根不在 `[repos]` 路径集合时产生 `UNREGISTERED_REPOSITORY` / `BLOCKED`；
- 不递归扫描项目内部 worktree、fixture 或 vendor 目录。

### Remote 与 verification

- `remote_policy=required` 且 `git remote` 为空时产生 `REPOSITORY_REQUIRED_REMOTE_MISSING` / `BLOCKED`。
- `remote_policy=optional` 不要求 remote。
- verification 命令为空数组时表示未声明工作区级命令，不产生 WARN。
- 非空命令不可执行时继续产生既有 `*_COMMAND_UNAVAILABLE` / `WARN`。

## 错误处理与兼容性

- manifest 结构或枚举非法继续返回 `MANIFEST_INVALID` / `ERROR`。
- `--repo` 的选择逻辑保持按 canonical `[repos]` 路径精确匹配。
- 全局 preflight 和 `--repo` preflight 都执行 managed-link 与未登记一级仓库检查，因为它们属于工作区完整性，不属于单仓状态。
- 本阶段不自动安装链接、创建 remote 或删除任何目录；只报告状态。

## 验证

- Manifest 测试覆盖当前 8 个仓库和三张严格同 key 表。
- Preflight 测试覆盖正确、缺失、错误目标的 managed link。
- 未登记一级 Git 根必须阻断；repository root 外目录和嵌套 Git/worktree 不应进入扫描。
- required/optional/upstream remote 三种情况均有测试。
- 空 verification 静默，非空无效命令继续 WARN。

## 面向使用者的操作说明

- `workspace.md` 说明八个受管项目的职责分类、metadata 合同、managed links 与
  一级仓库漂移门禁；不复制会随工作树变化的 Git 状态。
- README 提供 JSON preflight 命令，并明确它同时覆盖登记项目和 `repo/` 一级
  仓库发现。
- 空 `test_command` 或 `verify_command` 只表示未声明统一的工作区级命令，不能
  被解释为项目已经验证通过；使用者仍须遵循项目自身的验收合同。
- 完整测试：`python3 -m pytest tests/test_workspace_manifest.py tests/test_workspace_preflight.py tests/test_task_protocol.py -q`。

## 发布与回滚

代码合并后，从持久源 `/Users/fujie/.dotfiles/code-workspace/scripts/install-links` 安装 `scripts/`、`templates/`，安装 journal 放在目标目录和源仓库之外。安装前后分别运行 JSON preflight；若安装失败，使用 journal 执行可恢复移除，不手工覆盖已有路径。
