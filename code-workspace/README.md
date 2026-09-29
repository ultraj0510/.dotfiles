# code workspace

Codex / Claude Code が利用する個人ワークスペースの実行ビュー。

## ディレクトリ構成

```
/Users/fujie/code/
├── README.md                    ← このファイル（~/.dotfiles から配備される実行ビュー）
├── CLAUDE.md                    ← Claude Code ワークスペースエントリポイント
├── workspace.md                 ← 人向けの共有ガイド・責務境界
├── workspace.toml               ← 機械可読な構造・パス・既定値・ルールの権威
├── docs/                        ← 永続化する計画・教訓・レビュー
│   ├── plans/                   ← 現行の実装計画
│   ├── archive/                 ← 完了した計画
│   └── lessons.md               ← 継続的な教訓
├── runtime/
│   └── tasks/                   ← 実行中タスクの一時状態
└── repo/                        ← 独立 git リポジトリ群（台帳は workspace.toml の [repos]）
```

この構成のGit管理上の原本は `/Users/fujie/.dotfiles/code-workspace` にある。
パス、既定ディレクトリ、コマンド、ルール値は `workspace.toml`（特に
`[workspace]` と `[rules]`）を参照し、このREADMEには重複定義しない。

## 工作区 preflight

受管链接已经部署时，在运行视图 `/Users/fujie/code` 中执行：

```bash
scripts/preflight --json
```

部署前，或在持久源/源码检出根验证时，执行：

```bash
code-workspace/scripts/preflight --manifest code-workspace/workspace.toml --json
```

第二个命令使用源码检出中的脚本与 manifest；在运行视图的受管链接尚未部署时，
不要把它误当作运行视图入口。

preflight 除了检查 manifest 已登记的项目，还会检查 `repo/` 下的一级 Git
根是否全部登记；未登记一级仓库、受管 `scripts/` 或 `templates/` 链接缺失或
指向错误、以及 `remote_policy = "required"` 却没有 remote，都会返回
`BLOCKED`。它不递归扫描项目内部目录，也不会自动修复链接、创建 remote 或
修改项目仓库。

`[verification.<项目>]` 中的空 `test_command` 或 `verify_command` 表示该项目
未声明统一的工作区级命令；这不是验证通过，也不替代该项目自身的验收要求。
只有非空命令会被检查其在项目内是否可用。
