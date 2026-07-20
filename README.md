# dotfiles

Claude Code と個人の開発ワークスペースを管理するための dotfiles リポジトリです。

このリポジトリは、Claude Code のグローバル指示、プラグイン一覧、自作スキル、Git設定、株式ポートフォリオ取得の共通コード、Codex/Claude Code 兼用ワークスペース設定をまとめて管理します。

## セットアップ

### 新しい環境

```bash
curl -fsSL https://raw.githubusercontent.com/ultraj0510/.dotfiles/main/bootstrap.sh | bash
```

`bootstrap.sh` は `~/.dotfiles` が存在しない場合は clone し、存在する場合は `git pull` してから `install.sh` を実行します。

### 手動インストール

```bash
bash ~/.dotfiles/install.sh
```

`install.sh` は冪等です。既存ファイルがある場合は `~/.dotfiles-backup/<timestamp>/` に退避してから symlink を作成します。

## 管理対象

```text
~/.dotfiles/
├── bootstrap.sh                 # 新環境向け bootstrap
├── install.sh                   # symlink 作成と Claude Code plugin セットアップ
├── bash/
│   └── aliases.sh               # shell alias
├── claude/
│   ├── CLAUDE.md                # Claude Code user-level instructions
│   ├── marketplaces.txt         # Claude Code plugin marketplaces
│   ├── plugins.txt              # install 対象 plugin
│   ├── settings.json            # Claude Code settings template/reference
│   ├── settings.local.json      # local permissions/settings
│   └── skills/                  # Claude Code custom skills
├── code-workspace/
│   ├── AGENTS.md                # Codex workspace entrypoint
│   ├── CLAUDE.md                # Claude Code workspace entrypoint
│   ├── workspace.md             # shared workspace rules
│   ├── workspace.toml           # machine-readable workspace manifest
│   └── docs/                    # plans, lessons, archived notes
├── git/
│   └── .gitconfig               # Git config
├── portfolio-core/              # SBI portfolio auth/fetch shared implementation
└── tests/                       # regression tests
```

## `install.sh` が作るリンク

| Source | Link |
|--------|------|
| `git/.gitconfig` | `~/.gitconfig` |
| `bash/aliases.sh` | `~/.claude/bash_aliases.sh` |
| `claude/settings.local.json` | `~/.claude/settings.local.json` |
| `claude/CLAUDE.md` | `~/.claude/CLAUDE.md` |
| `claude/skills/` | `~/.claude/skills` |

## Claude Code plugins

`install.sh` は Claude Code が利用可能な場合に、次を自動セットアップします。

1. `claude/marketplaces.txt` に定義された marketplace を登録または更新
2. `claude/plugins.txt` に定義された plugin をインストール
3. `claude/skills/` を `~/.claude/skills` に symlink

現在の主な plugin:

- `superpowers`
- `github`
- `frontend-design`
- `code-review`
- `playwright`
- `skill-creator`
- `claude-md-management`
- `microsoft-docs`
- `oh-my-claudecode`

## Custom skills

`claude/skills/` には、個人運用向けの Claude Code skill を置いています。

| Skill | Purpose |
|-------|---------|
| `download-photos` | 写真販売サイトのカート画像ダウンロード |
| `omc-reference` | Oh My Claude Code 参照 |

株式分析関連の skills（`stock-*`、`portfolio-*`、`deep-analyze`）と共有ライブラリは
[stock-analysis](~/code/repo/stock-analysis/) に独立プロジェクトとして移行済み。
`claude/skills/` 以下のそれらは symlink で新プロジェクトを指している。

## Code workspace

`code-workspace/` は Git 管理上の原本で、`/Users/fujie/code` は Codex / Claude Code が利用する実行ビューです。

- `code-workspace/workspace.md`: 人間向けの構造・運用ルール
- `code-workspace/workspace.toml`: パス、既定ディレクトリ、コマンド、ルール値の機械可読な唯一の manifest
- `code-workspace/AGENTS.md`: Codex entrypoint
- `code-workspace/CLAUDE.md`: Claude Code project entrypoint
- `code-workspace/docs/plans/`: durable plans
- `code-workspace/docs/lessons.md`: correction lessons

実行中タスクの一時状態、永続化する計画、完了済み計画、教訓の既定位置は
`workspace.toml` の `[workspace]` を参照します。旧 `tasks/` は非権威の履歴です。

## セキュリティ方針

- Cookie、token、`.env`、SBI証券のセッション情報、実ポートフォリオデータはコミットしません。
- 生成物や一時状態は `runtime/`、`scratch/`、または ignore 済みディレクトリに置きます。
- `portfolio.yaml` や分析結果は公開repoに含めず、必要な場合は redacted example のみ管理します。

## テスト

Cookie更新まわりの回帰テストと Python 構文チェックは [stock-analysis](~/code/repo/stock-analysis/) プロジェクトに移行済み。

## 運用メモ

- READMEは公開repoの入口なので、個人情報や運用中の証券データを書かない。
- `code-workspace/workspace.toml` を先に更新し、その後に `workspace.md` やREADMEを更新する。
- 新しいタスクや計画の保存先をREADME側で再定義せず、`workspace.toml` の `[workspace]` に従う。
- 提交语言などの機械可判定ルールは `workspace.toml` の `[rules]` に従う。
