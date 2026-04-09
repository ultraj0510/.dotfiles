#!/usr/bin/env bash
# dotfiles install script - creates symlinks from dotfiles to home directory
set -e

DOTFILES="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$HOME/.dotfiles-backup/$(date +%Y%m%d_%H%M%S)"

backup_and_link() {
  local src="$1"  # dotfiles内のパス
  local dst="$2"  # リンク先（ホームの実際のパス）
  local rel="$3"  # dstから見たsrcへの相対パス

  mkdir -p "$(dirname "$dst")"

  # 既にリンク先が正しいsymlinkなら何もしない
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$rel" ]; then
    echo "  skip (already linked): $dst"
    return
  fi

  # 実ファイルが存在する場合はバックアップして削除
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    mkdir -p "$BACKUP_DIR"
    cp -r "$dst" "$BACKUP_DIR/"
    echo "  backup: $dst → $BACKUP_DIR/"
    if ! rm -rf "$dst" 2>/dev/null; then
      echo "  skip (bind mount, cannot replace): $dst"
      return
    fi
  elif [ -L "$dst" ]; then
    rm "$dst"
  fi

  ln -s "$rel" "$dst"
  echo "  linked: $dst → $rel"
}

echo "==> Installing dotfiles..."

# git
backup_and_link \
  "$DOTFILES/git/.gitconfig" \
  "$HOME/.gitconfig" \
  ".dotfiles/git/.gitconfig"

# claude aliases & settings（相対symlinkでホスト・コンテナ両対応）
mkdir -p "$HOME/.claude"
backup_and_link \
  "$DOTFILES/bash/aliases.sh" \
  "$HOME/.claude/bash_aliases.sh" \
  "../.dotfiles/bash/aliases.sh"

backup_and_link \
  "$DOTFILES/claude/settings.local.json" \
  "$HOME/.claude/settings.local.json" \
  "../.dotfiles/claude/settings.local.json"

backup_and_link \
  "$DOTFILES/claude/CLAUDE.md" \
  "$HOME/.claude/CLAUDE.md" \
  "../.dotfiles/claude/CLAUDE.md"

backup_and_link \
  "$DOTFILES/claude/agents" \
  "$HOME/.claude/agents" \
  "../.dotfiles/claude/agents"

# .bashrc に source 行を追記（重複しない）
BASHRC="$HOME/.bashrc"
SOURCE_LINE='[ -f ~/.dotfiles/bash/aliases.sh ] && source ~/.dotfiles/bash/aliases.sh'
if ! grep -qF "$SOURCE_LINE" "$BASHRC" 2>/dev/null; then
  echo "" >> "$BASHRC"
  echo "# dotfiles" >> "$BASHRC"
  echo "$SOURCE_LINE" >> "$BASHRC"
  echo "  updated: ~/.bashrc"
fi

# プラグイン自動インストール
PLUGINS_FILE="$DOTFILES/claude/plugins.txt"
if [ -f "$PLUGINS_FILE" ] && command -v claude &>/dev/null; then
  echo "==> Installing Claude Code plugins..."

  # marketplace が未登録なら追加・更新
  if ! claude plugin marketplace list 2>/dev/null | grep -q "claude-plugins-official"; then
    echo "  registering marketplace..."
    claude plugin marketplace add anthropics/claude-plugins-official 2>&1 | sed 's/^/    /'
  else
    claude plugin marketplace update claude-plugins-official 2>/dev/null | sed 's/^/    /' || true
  fi

  grep -v '^\s*#' "$PLUGINS_FILE" | grep -v '^\s*$' | while read -r plugin; do
    if claude plugin list 2>/dev/null | grep -A4 "$plugin@" | grep -q "enabled"; then
      echo "  skip (already installed): $plugin"
    else
      echo "  installing: $plugin"
      claude plugin install "$plugin@claude-plugins-official" 2>&1 | sed 's/^/    /'
    fi
  done
fi

echo "==> Done!"
