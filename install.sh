#!/usr/bin/env bash
# dotfiles install script - creates symlinks from dotfiles to home directory
set -e

DOTFILES="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$HOME/.dotfiles-backup/$(date +%Y%m%d_%H%M%S)"

backup_and_link() {
  local src="$1"  # dotfiles内のパス
  local dst="$2"  # リンク先（ホームの実際のパス）
  local rel="$3"  # dstから見たsrcへの相対パス

  if [ ! -e "$src" ] && [ ! -L "$src" ]; then
    echo "  BLOCKED: source does not exist: $src" >&2
    return 2
  fi
  local expected resolved
  expected="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$src")"
  resolved="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.join(os.path.dirname(sys.argv[1]), sys.argv[2])))' "$dst" "$rel")"
  if [ "$resolved" != "$expected" ]; then
    echo "  BLOCKED: link text does not resolve to source: $dst → $rel" >&2
    return 2
  fi

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
    echo "  BLOCKED: refusing to replace existing symlink: $dst → $(readlink "$dst")" >&2
    return 2
  fi

  ln -s "$rel" "$dst"
  echo "  linked: $dst → $rel"
}

echo "==> Installing dotfiles..."

"$DOTFILES/code-workspace/scripts/install-links" \
  --target-root "$HOME/code" \
  --state-file "$BACKUP_DIR/workspace-links.json"
echo "  workspace link rollback state: $BACKUP_DIR/workspace-links.json"

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
  "$DOTFILES/claude/skills" \
  "$HOME/.claude/skills" \
  "../.dotfiles/claude/skills"

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
    MARKETPLACE_CACHE_DIR="$HOME/.cache/dotfiles/marketplaces"
    MARKETPLACE_TTL="${DOTFILES_MARKETPLACE_TTL:-21600}"  # default: 6時間
    _now=$(date +%s)

    # 全marketplaceがTTL内か判定（trueなら高価なCLI呼び出しを丸ごとスキップ）
    _all_fresh=true
    while read -r _repo _mid; do
      _cf="$MARKETPLACE_CACHE_DIR/$_mid"
      if [ ! -f "$_cf" ] || [ $(( _now - $(cat "$_cf") )) -ge "$MARKETPLACE_TTL" ]; then
        _all_fresh=false; break
      fi
    done < <(grep -v '^\s*#' "$MARKETPLACES_FILE" | grep -v '^\s*$')

    if $_all_fresh; then
      while read -r _repo _mid; do
        echo "  skip (fresh, $(( _now - $(cat "$MARKETPLACE_CACHE_DIR/$_mid") ))s old): $_mid"
      done < <(grep -v '^\s*#' "$MARKETPLACES_FILE" | grep -v '^\s*$')
    else
      REGISTERED=$(claude plugin marketplace list 2>/dev/null)

      _update_marketplace() {
        local marketplace_id="$1"
        local cache_file="$MARKETPLACE_CACHE_DIR/$marketplace_id"
        local now; now=$(date +%s)

        if [ -f "$cache_file" ]; then
          local last; last=$(cat "$cache_file")
          local age=$(( now - last ))
          if [ "$age" -lt "$MARKETPLACE_TTL" ]; then
            echo "  skip (fresh, ${age}s old): $marketplace_id"
            return
          fi
        fi

        echo "  updating: $marketplace_id"
        claude plugin marketplace update "$marketplace_id" 2>&1 | sed 's/^/    /' || true

        mkdir -p "$MARKETPLACE_CACHE_DIR"
        date +%s > "$cache_file"
      }

      while read -r repo marketplace_id; do
        if echo "$REGISTERED" | grep -q "$marketplace_id"; then
          _update_marketplace "$marketplace_id" &
        else
          echo "  registering: $marketplace_id ($repo)"
          claude plugin marketplace add "$repo" 2>&1 | sed 's/^/    /'
        fi
      done < <(grep -v '^\s*#' "$MARKETPLACES_FILE" | grep -v '^\s*$')
      wait
    fi
  fi

  # プラグインのインストール
  if [ -f "$PLUGINS_FILE" ]; then
    echo "==> Installing Claude Code plugins..."
    PLUGIN_LIST=$(claude plugin list 2>/dev/null)
    grep -v '^\s*#' "$PLUGINS_FILE" | grep -v '^\s*$' | while read -r plugin_spec; do
      plugin_name="${plugin_spec%%@*}"
      if echo "$PLUGIN_LIST" | grep -A4 "$plugin_name@" | grep -q "enabled"; then
        echo "  skip (already installed): $plugin_spec"
      else
        echo "  installing: $plugin_spec"
        claude plugin install "$plugin_spec" 2>&1 | sed 's/^/    /'
      fi
    done
  fi
fi

echo "==> Done!"
