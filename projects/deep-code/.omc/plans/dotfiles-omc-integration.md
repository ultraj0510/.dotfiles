# Plan: dotfiles を OMC 標準利用に修正

## Status: pending approval (v3.1 — Architect V3 + Critic V3 approved, 15 verification steps)

## RALPLAN-DR Summary

### Principles
1. **OMC-first**: OMC の設定を dotfiles 管理下でも維持し、OMC なしでは機能しない状態にしない
2. **最小変更**: 既存のユーザー設定・スキル・プラグインを破壊しない
3. **再現可能**: `install.sh` 実行後に OMC が正常に動作すること
4. **逆方向互換**: dotfiles 側の変更は、OMC 未インストール環境では無害であること

### Decision Drivers
1. **OMC マーカー維持**: CLAUDE.md に `<!-- OMC:START -->` / `<!-- OMC:END -->` が必須
2. **skills 共存**: dotfiles スキルと OMC スキルを同一ディレクトリで共存させる
3. **冗長 statusLine 排除**: dotfiles の `statusLine` 設定が OMC HUD を上書きしない
4. **新規マシンでの再現性**: マーケットプレイス登録を含め、install.sh 一発で OMC が使えること

### Viable Options

**Option A: dotfiles 側を OMC 対応に更新（採用）**
- Pros: 変更が dotfiles 側に閉じる、OMC インストール状態に関わらず動作、install.sh 再実行で OMC 設定が維持される
- Cons: dotfiles リポジトリの変更が必要、OMC バージョンアップ時に CLAUDE.md のマーカー内コンテンツが古くなる可能性 → workflow で対応

**Option B: install.sh で OMC マーカーを後付けマージ**
- Pros: dotfiles 側の変更が少ない
- Cons: マージロジックが複雑になり壊れやすい、OMC 未インストール時の分岐が必要

**Invalidation rationale for Option B**: `backup_and_link` の宣言的 symlink モデルに動的マージを混ぜると、順序依存・エッジケース・テスト困難性が導入される。OMC セットアップが `/oh-my-claudecode:omc-setup` で独立管理できるため、複雑なマージロジックを install.sh に持ち込む価値はない。

**Architect's hybrid (post-install injection) の検討**: Architect は CLAUDE.md の OMC ブロックのみ install.sh で動的注入するハイブリッド案を提案した。これは Option B より単純だが、install.sh に「OMC インストール済みか」の分岐を導入することになり、dotfiles 単体での冪等性が損なわれる。また、すでに `~/.claude/CLAUDE.md` には OMC ブロックが存在しており、これを dotfiles 側に逆反映する今回の方向性と整合する。CLAUDE.md の symlink 書き戻し問題はワークフローで対処する。

---

## Requirements Summary

現在の dotfiles は OMC 未導入状態の設定で構成されている。OMC を標準利用するために、OMC 設定が `install.sh` 実行後も維持されるよう dotfiles 側を修正する。

## 変更内容

### 1. `claude/CLAUDE.md` — OMC マーカー追加

現在の `~/.dotfiles/claude/CLAUDE.md` は純粋なユーザー指示のみ。現在の `~/.claude/CLAUDE.md` は OMC ブロック + ユーザー指示の構造になっている。dotfiles の CLAUDE.md は `~/.claude/CLAUDE.md` への symlink となるため、OMC ブロックを含める必要がある。

**事前確認**: `ls -la ~/.dotfiles/claude/CLAUDE.md` でファイル所有者を確認。root 所有の場合は `sudo chown $USER:$USER ~/.dotfiles/claude/CLAUDE.md` で修正する。

**実装方法**: 現在の `~/.claude/CLAUDE.md` の内容（OMC ブロック + ユーザー指示）を dotfiles 側に**完全上書きコピー**する。`~/.claude/CLAUDE.md` はすでにこの構造になっているため、それを逆反映する形。

**symlink 書き戻し問題**: `~/.claude/CLAUDE.md` は dotfiles への symlink となる。OMC バージョンアップ時に `/oh-my-claudecode:omc-setup` が CLAUDE.md を更新すると、symlink を通じて dotfiles 側のファイルが変更される。これは git 管理下での uncommitted change となる。

**ワークフロー**: OMC アップグレード後、dotfiles リポジトリで `git diff` を確認し、CLAUDE.md の OMC ブロック変更をコミットする。

**対象ファイル**: `~/.dotfiles/claude/CLAUDE.md`

### 2. `claude/skills/` — omc-reference スキル追加

OMC セットアップがインストールする `omc-reference` スキルを dotfiles の skills ディレクトリに追加する。

**事前確認**: `test -d ~/.claude/skills/omc-reference/` で存在確認。OMC がインストールされていないマシンでは、先に `claude plugin install oh-my-claudecode@omc` を実行する。

**正規ソースパス**: `~/.claude/plugins/cache/omc/oh-my-claudecode/4.14.1/skills/omc-reference/`
（注: このパスは OMC プラグインキャッシュの正規パス。OMC が現在インストールされているマシンでのみ有効。新規マシンでは、`claude plugin install oh-my-claudecode@omc` が実行された後に omc-reference が利用可能になる）

**実装方法**: 現在の `~/.claude/skills/omc-reference/` を `~/.dotfiles/claude/skills/omc-reference/` にコピーする。

**対象ディレクトリ**: `~/.dotfiles/claude/skills/omc-reference/`

### 3. `claude/settings.local.json` — statusLine 削除

現在の `settings.local.json` には `statusLine` が設定されており、これが OMC HUD の `statusLine` 設定（`~/.claude/settings.json`）と競合する。OMC HUD を優先するため削除する。

**変更**: `statusLine` キーを削除

**対象ファイル**: `~/.dotfiles/claude/settings.local.json`

### 4. `claude/statusline.sh` — 削除

`statusLine` 削除に伴い、`statusline.sh` は参照されないデッドコードとなる。削除する。

**変更**: `~/.dotfiles/claude/statusline.sh` を削除し、`install.sh` の対応する `backup_and_link` 行も削除

**対象ファイル**: `~/.dotfiles/claude/statusline.sh`, `~/.dotfiles/install.sh`

### 5. `claude/marketplaces.txt` — OMC マーケットプレイス追加

OMC プラグインのインストールには `omc` マーケットプレイスの登録が必須。現在の `marketplaces.txt` に `omc` が含まれていないため、新規マシンで `claude plugin install oh-my-claudecode@omc` が失敗する。

**追加行**:
```
https://github.com/ultraj0510/oh-my-claudecode.git    omc
```

**対象ファイル**: `~/.dotfiles/claude/marketplaces.txt`

### 6. `claude/plugins.txt` — OMC プラグイン追加

**追加行**:
```
oh-my-claudecode@omc
microsoft-docs@claude-plugins-official
```

`microsoft-docs@claude-plugins-official` はユーザーが Azure/Microsoft 技術スタックを常用しており、すでに `~/.claude/settings.json` の `enabledPlugins` で有効化されているため、新規マシンでの再現性のために追加する。

**対象ファイル**: `~/.dotfiles/claude/plugins.txt`

### 7. `install.sh` — agents ディレクトリの symlink 削除

現在の `install.sh` は空の `claude/agents/` ディレクトリを `~/.claude/agents` に symlink している。OMC が将来エージェント設定を `~/.claude/agents/` に配置する場合、この空 symlink が shadow してしまう。agents ディレクトリは現在未使用のため、symlink 行を削除する。

**変更**:
- `install.sh` の `claude/agents` に関する `backup_and_link` 呼び出しを削除
- 既存の `~/.claude/agents` symlink を削除（`rm ~/.claude/agents`）
- 既存の `~/.claude/statusline.sh` symlink を削除（`rm -f ~/.claude/statusline.sh`、存在する場合）

**対象ファイル**: `~/.dotfiles/install.sh`

### 8. `install.sh` 再実行

Steps 1-7 で dotfiles 側のファイルを修正した後、`install.sh` を実行して変更を `~/.claude/` に反映する。`~/.claude/CLAUDE.md` は現在通常ファイルだが、install.sh 実行後は `~/.dotfiles/claude/CLAUDE.md` への symlink になる。

**実行**: `cd ~/.dotfiles && bash install.sh`

## Acceptance Criteria

1. `install.sh` 実行後、`~/.claude/CLAUDE.md` に `<!-- OMC:START -->` と `<!-- OMC:END -->` が存在する
2. `install.sh` 実行後、`~/.claude/skills/omc-reference/` が存在する
3. `install.sh` 実行後、`~/.claude/settings.local.json` に `statusLine` キーが存在しない
4. `install.sh` 実行後、`~/.claude/statusline.sh` が存在しない
5. `install.sh` 実行後、`~/.dotfiles/claude/marketplaces.txt` に `omc` エントリが存在する
6. `install.sh` 実行後、OMC のスラッシュコマンド（`/autopilot`, `/team` 等）が利用可能
7. 既存の dotfiles スキル（stock-analyze, deep-analyze 等）が引き続き利用可能
8. `~/.claude/agents` が存在しない（symlink されていない）

## Implementation Steps

| Step | File | Action |
|------|------|--------|
| 1 | `~/.dotfiles/claude/CLAUDE.md` | 現在の `~/.claude/CLAUDE.md` の内容（OMC ブロック + ユーザー指示）をコピー |
| 2 | `~/.dotfiles/claude/skills/omc-reference/` | `~/.claude/skills/omc-reference/` をコピー |
| 3 | `~/.dotfiles/claude/settings.local.json` | `statusLine` キーを削除 |
| 4 | `~/.dotfiles/claude/statusline.sh` | ファイルを削除 |
| 5 | `~/.dotfiles/claude/marketplaces.txt` | `https://github.com/ultraj0510/oh-my-claudecode.git    omc` を追記 |
| 6 | `~/.dotfiles/claude/plugins.txt` | `oh-my-claudecode@omc` と `microsoft-docs@claude-plugins-official` を追記 |
| 7 | `~/.dotfiles/install.sh` | agents symlink 行（`install.sh:63-66`）と statusline.sh symlink 行（`install.sh:68-71`）を削除、既存 `~/.claude/agents` と `~/.claude/statusline.sh` symlink を削除 |
| 8 | `~/.dotfiles/install.sh` (実行) | `bash install.sh` を実行して変更を `~/.claude/` に反映 |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OMC アップグレードで CLAUDE.md のマーカー内容が古くなる | Medium | symlink により omc-setup の更新が dotfiles に伝播する。OMC アップグレード後、dotfiles リポジトリで `git diff` し変更をコミットする |
| OMC アップグレードで skills/omc-reference/ が更新される | Low | `~/.claude/skills/` も dotfiles への symlink のため、omc-setup が skills/ に書き込むと同様に uncommitted change が発生する。CLAUDE.md と同じワークフローで対処 |
| dotfiles の CLAUDE.md が OMC なし環境で冗長 | Low | OMC ブロックは HTML コメント内だが、運用指示が含まれる。OMC 未インストール時は無害な指示として扱われる |
| skills の二重管理 | Low | omc-reference の更新頻度は低い。OMC アップグレード時に再コピーする |
| 新規マシンで omc-reference のソース不在 | Low | Step 2 は OMC インストール済みマシンでのみ実行。対象パスは正規プラグインキャッシュパスを使用 |
| agents/ 削除による既存エージェント消失 | Low | 現在 agents/ は空。OMC も agents/ を使用していない |

## Verification Steps

1. `grep -c "OMC:START\|OMC:END" ~/.dotfiles/claude/CLAUDE.md` → 2
2. `ls ~/.dotfiles/claude/skills/omc-reference/SKILL.md` → 存在すること
3. `for s in stock-analyze deep-analyze stock-scan; do test -d ~/.dotfiles/claude/skills/$s || echo "MISSING: $s"; done` → 出力なし（既存スキルが維持されていること / AC #7）
4. `python3 -c "import json; d=json.load(open('$HOME/.dotfiles/claude/settings.local.json')); assert 'statusLine' not in d"` → エラーなし
5. `test -f ~/.dotfiles/claude/statusline.sh` → 存在しないこと
6. `grep -c "omc" ~/.dotfiles/claude/marketplaces.txt` → >= 1
7. `grep -c "oh-my-claudecode@omc" ~/.dotfiles/claude/plugins.txt` → >= 1
8. `grep -c "microsoft-docs@claude-plugins-official" ~/.dotfiles/claude/plugins.txt` → >= 1
9. `grep -c "claude/agents" ~/.dotfiles/install.sh` → 0
10. `grep -c "statusline.sh" ~/.dotfiles/install.sh` → 0
11. `test -L ~/.claude/agents` → 存在しないこと（symlink 削除済み）
12. `bash ~/.dotfiles/install.sh` → エラーなく完了すること（二回目の実行: Step 8 の実行後に再度 install.sh を実行し、冪等性を確認。全エントリが `skip (already linked)` または `skip (fresh)` となること）
13. `grep -c "OMC:START\|OMC:END" ~/.claude/CLAUDE.md` → 2（symlink 経由で反映）
14. `claude plugin list 2>/dev/null \| grep -q "oh-my-claudecode@omc" && echo "OK"` → "OK"（OMC プラグインが有効）
15. `cd ~/.dotfiles && git diff --stat` で全変更を最終確認

## Rollback

全変更は git で追跡可能。`install.sh` は変更前に `~/.dotfiles-backup/` に自動バックアップを作成する。問題が発生した場合:
- `cd ~/.dotfiles && git checkout -- claude/ install.sh` で dotfiles 側のファイルを復元
- `~/.dotfiles-backup/<timestamp>/` から上書きされたファイルを手動復元可能

## ADR

- **Decision**: dotfiles 側のファイルを直接修正し、OMC 設定を dotfiles 管理に含める（Option A）
- **Drivers**: 最小変更、再現可能性、OMC-first、新規マシン再現性
- **Alternatives considered**:
  - install.sh での動的マージ（Option B）— 複雑度が高く維持困難なため棄却
  - Architect's hybrid（CLAUDE.md のみ動的注入）— install.sh に OMC 検出分岐を導入することになり、シンプルさが損なわれるため棄却
- **Why chosen**: Option A は dotfiles の設計思想（symlink で状態を管理）と整合し、OMC の有無に関わらず安全。CLAUDE.md の symlink 書き戻しは OMC アップグレード時のワークフローで対処可能
- **Consequences**: OMC バージョンアップ時に dotfiles リポジトリに uncommitted change が発生する。アップグレード後、変更を確認してコミットするワークフローが必要
- **Follow-ups**: OMC メジャーアップデート時に CLAUDE.md と omc-reference の更新を検討

## Changelog

- v3.1: Architect V3 + Critic V3 レビュー反映
  - Step 7 に `rm -f ~/.claude/statusline.sh` を追加（Architect V3 #1）
  - Step 7 の install.sh 編集に行番号参照を追加（Critic V3 MINOR #2）
  - Step 1 にファイル所有者確認の事前チェックを追加（Critic V3 gap）
  - Step 2 に OMC インストール済み確認の事前チェックを追加（Critic V3 MINOR #5）
  - Risks に skills/ symlink 書き戻しリスクを追加（Architect V3 #2）
  - VS #3 追加: 既存スキル維持確認（Critic V3 MINOR #1）
  - VS #12 に二回目実行であることの注記を追加（Critic V3 MINOR #3）
  - Rollback セクションを追加（Critic V3 MINOR #4）
- v3: Critic V2 レビュー反映
  - Step 7 に既存 `~/.claude/agents` symlink の削除を追加（Critic MAJOR #1）
  - Step 8 追加: `install.sh` 再実行（Critic MINOR #1）
  - Step 6 に microsoft-docs 追加の理由を明記（Critic MINOR #3）
  - Verification Steps に OMC プラグイン有効確認を追加（Critic MAJOR #2）
  - Verification Steps に install.sh 実行後の `~/.claude/` パス確認を追加
- v2: Architect + Critic レビュー反映
  - Step 4 追加: `statusline.sh` 削除
  - Step 5 追加: `marketplaces.txt` に omc エントリ追加（Critic MAJOR #1）
  - Step 7 追加: `install.sh` から agents symlink と statusline.sh symlink 削除（Architect #3, Critic MAJOR #3）
  - ADR に hybrid 案の検討と棄却理由を追記（Critic MAJOR #2 相当）
  - Risks に symlink 書き戻し問題のワークフロー対処を明記（Critic MAJOR #2）
  - Verification Steps を具体化し、marketplaces/agents/statusline.sh のチェックを追加
