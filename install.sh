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
MARKETPLACES_FILE="$DOTFILES/claude/marketplaces.txt"
PLUGINS_FILE="$DOTFILES/claude/plugins.txt"

if command -v claude &>/dev/null; then
  # marketplaces の登録・更新
  if [ -f "$MARKETPLACES_FILE" ]; then
    echo "==> Setting up Claude Code marketplaces..."
    REGISTERED=$(claude plugin marketplace list 2>/dev/null)
    grep -v '^\s*#' "$MARKETPLACES_FILE" | grep -v '^\s*$' | while read -r repo marketplace_id; do
      if echo "$REGISTERED" | grep -q "$marketplace_id"; then
        echo "  updating: $marketplace_id"
        claude plugin marketplace update "$marketplace_id" 2>&1 | sed 's/^/    /' || true
      else
        echo "  registering: $marketplace_id ($repo)"
        claude plugin marketplace add "$repo" 2>&1 | sed 's/^/    /'
      fi
    done
  fi

  # プラグインのインストール
  if [ -f "$PLUGINS_FILE" ]; then
    echo "==> Installing Claude Code plugins..."
    grep -v '^\s*#' "$PLUGINS_FILE" | grep -v '^\s*$' | while read -r plugin_spec; do
      plugin_name="${plugin_spec%%@*}"
      if claude plugin list 2>/dev/null | grep -A4 "$plugin_name@" | grep -q "enabled"; then
        echo "  skip (already installed): $plugin_spec"
      else
        echo "  installing: $plugin_spec"
        claude plugin install "$plugin_spec" 2>&1 | sed 's/^/    /'
      fi
    done
  fi
fi

# ローカルプラグインのインストール
# claude plugin install はマーケットプレイス形式のみ対応のため、JSON直接編集で登録する
LOCAL_PLUGINS_DIR="$DOTFILES/claude/local-plugins"
INSTALLED_PLUGINS_JSON="$HOME/.claude/plugins/installed_plugins.json"
SETTINGS_JSON="$HOME/.claude/settings.json"

if [ -d "$LOCAL_PLUGINS_DIR" ]; then
  echo "==> Installing local plugins..."
  for plugin_dir in "$LOCAL_PLUGINS_DIR"/*/; do
    [ -d "$plugin_dir/.claude-plugin" ] || continue
    plugin_name=$(basename "$plugin_dir")
    plugin_key="${plugin_name}@local"
    install_path="$(cd "$plugin_dir" && pwd)"

    already=$(python3 -c "
import json, sys, os
path = '$INSTALLED_PLUGINS_JSON'
if not os.path.exists(path): sys.exit(1)
d = json.load(open(path))
sys.exit(0 if '$plugin_key' in d.get('plugins', {}) else 1)
" 2>/dev/null && echo "yes" || echo "no")

    if [ "$already" = "yes" ]; then
      echo "  skip (already installed): $plugin_name"
    else
      echo "  installing local plugin: $plugin_name"
      python3 - <<PYEOF
import json, os
from datetime import datetime, timezone

now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

# installed_plugins.json に登録
ip = '$INSTALLED_PLUGINS_JSON'
d = json.load(open(ip)) if os.path.exists(ip) else {'version': 2, 'plugins': {}}
d.setdefault('plugins', {})['$plugin_key'] = [{
    'scope': 'user',
    'installPath': '$install_path',
    'version': 'local',
    'installedAt': now,
    'lastUpdated': now,
}]
json.dump(d, open(ip, 'w'), indent=2)

# settings.json で有効化
sp = '$SETTINGS_JSON'
s = json.load(open(sp)) if os.path.exists(sp) else {}
s.setdefault('enabledPlugins', {})['$plugin_key'] = True
json.dump(s, open(sp, 'w'), indent=2)

print('    registered: $plugin_key -> $install_path')
PYEOF
    fi
  done
fi

echo "==> Done!"
