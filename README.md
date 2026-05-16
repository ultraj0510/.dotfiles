# dotfiles

Claude Code 環境の個人設定を管理するリポジトリ。  
WSL2 ホストとdevcontainerの両方で動作するよう、相対シンボリックリンクで構成されています。

## 使い方

### 新しい環境でのセットアップ

```bash
# bootstrap（dotfiles クローン + install.sh 実行）
curl -fsSL https://raw.githubusercontent.com/ultraj0510/dotfiles/main/bootstrap.sh | bash
```

### 手動インストール

```bash
bash ~/.dotfiles/install.sh
```

`install.sh` は冪等です。再実行しても安全。

## ディレクトリ構成

```
~/.dotfiles/
├── install.sh              # シンボリックリンク作成 + プラグイン自動インストール
├── bootstrap.sh            # 新マシン初期セットアップ（git clone → install.sh）
├── bash/
│   └── aliases.sh          # API切り替えエイリアス（claude / claude-mimo）
├── claude/
│   ├── CLAUDE.md           # Claude グローバル指示（個人スタイル）
│   ├── settings.local.json # Claude ツール権限設定
│   ├── agents/             # 自作サブエージェント定義（*.md）
│   ├── local-plugins/      # 個人専用ローカルプラグイン（自動インストール）
│   │   ├── commit-push/    # git add → commit → push スキル
│   │   └── stock-analyze/  # 日本株分析スキル
│   ├── marketplaces.txt    # 登録するマーケットプレイス一覧
│   ├── plugins.txt         # 自動インストールするプラグイン一覧
│   └── statusline.sh       # ステータスライン表示スクリプト
└── git/
    └── .gitconfig          # Git設定
```

`install.sh` が作成するシンボリックリンク：

| dotfiles | → | リンク先 |
|----------|---|---------|
| `git/.gitconfig` | → | `~/.gitconfig` |
| `bash/aliases.sh` | → | `~/.claude/bash_aliases.sh` |
| `claude/CLAUDE.md` | → | `~/.claude/CLAUDE.md` |
| `claude/settings.local.json` | → | `~/.claude/settings.local.json` |
| `claude/agents/` | → | `~/.claude/agents/` |
| `claude/statusline.sh` | → | `~/.claude/statusline.sh` |

## プラグイン管理

`install.sh` は起動時に3種類のプラグインを自動セットアップします：

1. **マーケットプレイスの登録**（`claude/marketplaces.txt`）
2. **マーケットプレイス経由プラグインのインストール**（`claude/plugins.txt`）
3. **ローカルプラグインのインストール**（`claude/local-plugins/` 以下のディレクトリ）

## 3層管理モデル

| 層 | 管理場所 | 内容 |
|----|---------|------|
| 個人設定 | このリポジトリ（fork して使う） | 作業スタイル・個人プラグイン |
| チーム共有 | `org/claude-plugins`（社内マーケットプレイス） | 共通スキル・チームルール |
| プロジェクト固有 | 各リポジトリの `CLAUDE.md` | スタック固有ルール |

## チームへの展開

1. このリポジトリを fork
2. 自分の名前・言語設定などを `claude/CLAUDE.md` で編集
3. devcontainer 起動 → 社内マーケットプレイスが自動登録され、チームスキルが使える状態で起動
