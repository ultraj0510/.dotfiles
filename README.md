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
| `portfolio-auth` | SBI証券セッションCookieの保存・検証 |
| `portfolio-fetch` | SBI証券ポートフォリオ取得 |
| `portfolio-update` | 売買記録・保有銘柄更新 |
| `stock-advisor` | 朝のポートフォリオ確認と取引判断 |
| `stock-analyze` | 日本株テクニカル分析 |
| `stock-backtest` | シグナルのバックテスト |
| `stock-scan` | 保有銘柄のシグナルスキャン |
| `deep-analyze` | マルチエージェント深掘り分析 |
| `download-photos` | 写真販売サイトのカート画像ダウンロード |
| `omc-reference` | Oh My Claude Code 参照 |

SBI証券連携の共通実装は `portfolio-core/` に集約し、skill側は wrapper として扱います。

## Code workspace

`code-workspace/` は `/Users/fujie/code` 向けの Codex / Claude Code 共通設定です。

- `code-workspace/workspace.md`: 人間向けの構造・運用ルール
- `code-workspace/workspace.toml`: ツール向けの manifest
- `code-workspace/AGENTS.md`: Codex entrypoint
- `code-workspace/CLAUDE.md`: Claude Code project entrypoint
- `code-workspace/docs/plans/`: durable plans
- `code-workspace/docs/lessons.md`: correction lessons

`tasks/` は廃止済みです。作業計画や教訓は `code-workspace/docs/` に集約します。

## セキュリティ方針

- Cookie、token、`.env`、SBI証券のセッション情報、実ポートフォリオデータはコミットしません。
- 生成物や一時状態は `runtime/`、`scratch/`、または ignore 済みディレクトリに置きます。
- `portfolio.yaml` や分析結果は公開repoに含めず、必要な場合は redacted example のみ管理します。

## テスト

Cookie更新まわりの回帰テスト:

```bash
pytest -q tests/test_portfolio_auth_cookie_refresh.py
```

Python構文チェック:

```bash
python3 -m py_compile \
  portfolio-core/cookie_store.py \
  portfolio-core/sbi_auth.py \
  portfolio-core/sbi_fetch.py \
  claude/skills/portfolio-auth/auth_sbi.py \
  claude/skills/portfolio-fetch/scripts/fetch_portfolio.py
```

## 運用メモ

- READMEは公開repoの入口なので、個人情報や運用中の証券データを書かない。
- `code-workspace/workspace.toml` を先に更新し、その後に `workspace.md` やREADMEを更新する。
- 完了済みの一時計画は `tasks/` ではなく `code-workspace/docs/archive/` に残す。
