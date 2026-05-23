# Plan: stock-advisor と deep-code を dotfiles で一元管理

## Status: pending approval (v4 — Architect V1+V2 + Critic V1+V2 approved)

## RALPLAN-DR Summary

### Principles
1. **dotfiles 単一管理**: 設定・スクリプト・プロジェクトメモは dotfiles に集約し、新規マシンで `install.sh` 一発で再現できること
2. **既存構造を活かす**: `~/.claude/skills/` → `~/.dotfiles/claude/skills/` の symlink 構造はすでに機能している。このパターンを踏襲する
3. **不要成果物の分離**: .venv, cache, __pycache__, _workspace (旧LLM出力), logs など再現可能または自動生成される成果物は git 管理対象外にする
4. **最小変更**: 動いているものを壊さない。gitignore 追加と git add/commit が中心

### Decision Drivers
1. **再現性**: 新規マシンで `install.sh` 一発で全 symlink が作成され、`pip install -r requirements.txt` でスクリプトが動作すること
2. **シンプルさ**: 管理リポジトリを増やさない。dotfiles が唯一の source of truth
3. **整合性**: 既存の symlink パターン（skills, settings 等）と矛盾しない

### Viable Options

**stock-advisor scripts の管理**:
- **Option A: dotfiles にコミット（採用）** — scripts/ はすでに dotfiles 配下に物理配置されている。.gitignore で成果物を除外し、ソースコードのみを dotfiles で追跡する
- **Option B: 別リポジトリ + submodule** — 過剰。scripts は skill の一部であり、skill 全体がすでに dotfiles にある

**deep-code の管理**:
- **Option A: dotfiles に移動 + install.sh 更新（採用）** — `~/projects/deep-code/` を `~/.dotfiles/projects/deep-code/` に移動し、install.sh に symlink 作成行を追加。symlink により deep-code の git 操作は dotfiles リポジトリに対して行われる（単一コミット履歴は失われるが、現状の価値は軽微）
- **Option B: 別リポジトリのまま** — 「一元管理」の要望に反する
- **Option C: git submodule** — この規模のプロジェクトメモに submodule は複雑すぎる

**Invalidation rationale for alternatives**: Option B (別リポジトリ) はユーザーの「一元管理したい」に真っ向から反する。Option C (submodule) は deep-code の規模（数ファイルのプロジェクトメモ）に対して過剰設計。

---

## Requirements Summary

現在、stock-advisor の scripts/ は dotfiles 配下に物理配置されているが git untracked。deep-code は `/home/ultraj/projects/deep-code/` に独立した git リポジトリとして存在している。両方を dotfiles で一元管理する。

また、dotfiles リポジトリにはすでに承認済みの `dotfiles-omc-integration.md` プラン（OMC 設定の dotfiles 統合）が未実行で残っている。今回はこのプランの実行はスコープ外とし、別途対応する。

## 変更内容

### US-011: stock-advisor/scripts/ を dotfiles で追跡 + _workspace/ を git 管理から除外

**現状**:
- `~/.dotfiles/claude/skills/stock-advisor/scripts/` にスクリプトが物理配置されている
- git では untracked（`?? claude/skills/stock-advisor/scripts/`）
- `.venv/` (217MB), `cache/` (220KB), `__pycache__/`, `logs/` (空) が含まれる
- `_workspace/` (3つの旧LLM出力ファイル) がすでに git 追跡済み
- ソースファイル: `signal_engine.py`, `backtest_engine.py`, `data_utils.py`, `run_signal_engine`, `requirements.txt`, `default_tickers.txt`

**実装**:
1. `~/.dotfiles/claude/skills/stock-advisor/scripts/.gitignore` を作成
   ```
   .venv/
   cache/
   __pycache__/
   logs/
   *.pyc
   ```
2. `_workspace/` を git 管理から外す: `git rm --cached claude/skills/stock-advisor/_workspace/` + 親ディレクトリの `.gitignore` に `_workspace/` を追加
3. scripts/ のソースファイルを `git add` で追跡開始
4. コミット

### US-012: 修正済み SKILL.md を dotfiles にコミット

**現状**:
- `claude/skills/stock-advisor/SKILL.md` — modified (Step 2 の LLM パイプライン置き換え)
- `claude/skills/stock-backtest/SKILL.md` — modified (backtest_engine.py 参照に変更)
- `claude/skills/stock-scan/SKILL.md` — modified (signal_engine.py --all 参照に変更)

**実装**: 3ファイルをステージングしてコミット

### US-013: deep-code を dotfiles に移動 + install.sh 更新

**現状**:
- `/home/ultraj/projects/deep-code/` — 独立 git リポジトリ（root commit 1件）
- 内容: `.gitignore`, `.omc/prd.json`, `.omc/progress.txt`, `.omc/plans/` (3計画)
- `.omc/state/` と `.omc/sessions/` は既存 .gitignore で除外済み

**実装**:
1. `mkdir -p ~/.dotfiles/projects/deep-code/`
2. `rsync -av --exclude=.git ~/projects/deep-code/ ~/.dotfiles/projects/deep-code/` で .git を除外してコピー
3. dotfiles で `git add projects/deep-code/` してコミット (US-013)
4. `mv ~/projects/deep-code ~/projects/deep-code.bak` で元ディレクトリをバックアップ
5. `mkdir -p ~/projects && ln -s ~/.dotfiles/projects/deep-code ~/projects/deep-code` で symlink 作成
6. `~/.dotfiles/install.sh` に以下の行を追加（`# Projects symlinks` セクション）:
   ```bash
   # --- Projects symlinks ---
   mkdir -p "$HOME/projects"
   backup_and_link \
     "$DOTFILES/projects/deep-code" \
     "$HOME/projects/deep-code" \
     "../.dotfiles/projects/deep-code"
   ```

### US-014: dotfiles の git 状況を最終確認

**実装**:
1. `cd ~/.dotfiles && git status` で全変更を確認
2. `git diff --stat --cached` で変更概要を確認
3. 本プランに関係するパスのみが変更されていることを確認（既存の他変更は無視）
4. コミット

## Acceptance Criteria

1. `~/.dotfiles/claude/skills/stock-advisor/scripts/.gitignore` が存在し、`.venv/`, `cache/`, `__pycache__/`, `logs/`, `*.pyc` が指定されている
2. `cd ~/.dotfiles && git status` で `claude/skills/stock-advisor/scripts/` が untracked ではなく staged または committed である
3. dotfiles の git status で `.venv/` や `cache/` が追跡対象に入っていない
4. `~/.dotfiles/claude/skills/stock-advisor/SKILL.md` の変更がコミット済み
5. `~/.dotfiles/claude/skills/stock-backtest/SKILL.md` の変更がコミット済み
6. `~/.dotfiles/claude/skills/stock-scan/SKILL.md` の変更がコミット済み
7. `~/.dotfiles/projects/deep-code/.omc/prd.json` が存在する
8. `~/.dotfiles/projects/deep-code/.omc/progress.txt` が存在する
9. `grep -Eq "(^|/)state($|/)" ~/.dotfiles/projects/deep-code/.gitignore && grep -Eq "(^|/)sessions($|/)" ~/.dotfiles/projects/deep-code/.gitignore && echo OK` → OK（word boundary で `.gitignore` が state/sessions を正確に除外）
10. `~/projects/deep-code/` が `~/.dotfiles/projects/deep-code/` への symlink である
11. `grep -q "projects/deep-code" ~/.dotfiles/install.sh` → 成功（install.sh に deep-code symlink 行が存在）
12. `claude/skills/stock-advisor/_workspace/` が `git ls-files` に表示されない（git 追跡から除外済み）
13. `test -d ~/projects/deep-code.bak` → 成功（元ディレクトリがバックアップされている）

## Implementation Steps

| Step | Location | Action |
|------|----------|--------|
| 0 | dotfiles repo | **事前確認**: `grep -q "backup_and_link()" ~/.dotfiles/install.sh` で関数定義の存在を確認。なければ中断 |
| 1a | `~/.dotfiles/claude/skills/stock-advisor/scripts/.gitignore` | 作成: .venv/, cache/, __pycache__/, logs/, *.pyc を除外 |
| 1b | dotfiles repo | `git rm -r --cached claude/skills/stock-advisor/_workspace/` で旧LLM出力を追跡から外す（`-r` 必須: ディレクトリのため） |
| 1c | `~/.dotfiles/claude/skills/stock-advisor/.gitignore` | 作成: `_workspace/` を除外 |
| 2a | dotfiles repo | `git add` scripts/ のソースファイルと両 .gitignore |
| 2b | dotfiles repo | `git add` 修正済み SKILL.md x3 |
| 3a | dotfiles repo | コミット (US-011: scripts + _workspace cleanup) |
| 3b | dotfiles repo | コミット (US-012: SKILL.md updates) |
| 4 | `~/.dotfiles/projects/deep-code/` | `mkdir -p` でディレクトリ作成 |
| 5 | `~/.dotfiles/projects/deep-code/` | `rsync -av --exclude=.git ~/projects/deep-code/ ~/.dotfiles/projects/deep-code/` で .git を除外してコピー（source 末尾 `/` は中身コピーの意味。末尾なしだと `deep-code/deep-code/` になるので注意） |
| 6 | dotfiles repo | `git add projects/deep-code/` |
| 7 | dotfiles repo | コミット (US-013: deep-code migration) |
| 8 | `~/projects/` | `mv ~/projects/deep-code ~/projects/deep-code.bak` でバックアップ |
| 9 | `~/projects/` | `ln -s ~/.dotfiles/projects/deep-code ~/projects/deep-code` で symlink 作成 |
| 10 | `~/.dotfiles/install.sh` | `projects/deep-code` の `backup_and_link` 行を追加（Step 0 で関数定義確認済み） |
| 11 | dotfiles repo | `git add install.sh` してコミット (US-013: install.sh update) |
| 12 | dotfiles repo | 最終確認: `git status` で本プラン対象パスのみ変更済みであること、`git diff --stat --cached` が空であることを確認 |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| .venv の requirements.txt 再現性 | Low | requirements.txt は version-pinned。`pip install -r requirements.txt` で再現可能 |
| deep-code 移動で OMC のパス解決が壊れる | Medium | symlink `~/projects/deep-code → ~/.dotfiles/projects/deep-code` でパスを維持 |
| 元 deep-code の .git ディレクトリが dotfiles に混入 | Low | `rsync --exclude=.git` で除外 |
| dotfiles の git 履歴が膨張 | Low | .venv (217MB) は gitignore で除外済み。追加されるのは数 KB のソースファイルのみ |
| symlink 先が dotfiles git リポジトリ内にあるため、`~/projects/deep-code` での git 操作が dotfiles の状態を表示する | Low | ユーザーは `~/projects/deep-code/` で git 操作を行わない。OMC は `.omc/` ファイルの読み書きのみを行う |
| deep-code の単一コミット履歴が失われる | Low | 現状の deep-code はルートコミット 1 件のみで、失われる履歴価値はほぼない。元ディレクトリは `.bak` として保持される |
| 新規マシンで install.sh 実行後、pip install が必要 | Low | requirements.txt は scripts/ に含まれ、`pip install -r` は手動または別スクリプトで実行。install.sh を汚染しない判断 |
| `_workspace/` の旧 LLM 出力 | Low | `git rm --cached` で追跡から外し .gitignore で再追跡を防止。過去コミットの履歴には残るが実害なし |

## Verification Steps

1. `test -f ~/.dotfiles/claude/skills/stock-advisor/scripts/.gitignore` → 成功
2. `grep -c "venv\|cache\|logs\|pycache\|pyc" ~/.dotfiles/claude/skills/stock-advisor/scripts/.gitignore` → >= 4
3. `cd ~/.dotfiles && git status --short | grep "scripts/" | grep -v ".gitignore"` → staged ファイルのみ（untracked なし）
4. `cd ~/.dotfiles && git status --short | grep "\.venv"` → 出力なし
5. `cd ~/.dotfiles && git status --short | grep "SKILL.md"` → 出力なし（コミット済み）
6. `cd ~/.dotfiles && git ls-files | grep "_workspace"` → 出力なし（追跡除外済み）
7. `test -f ~/.dotfiles/projects/deep-code/.omc/prd.json` → 成功
8. `test -f ~/.dotfiles/projects/deep-code/.omc/progress.txt` → 成功
9. `grep -Eq "(^|/)state($|/)" ~/.dotfiles/projects/deep-code/.gitignore && grep -Eq "(^|/)sessions($|/)" ~/.dotfiles/projects/deep-code/.gitignore && echo OK` → OK（word boundary で `state`/`sessions` を正確にマッチ）
10. `test -L ~/projects/deep-code` → 成功（symlink）
11. `readlink ~/projects/deep-code` → `/home/ultraj/.dotfiles/projects/deep-code`
12. `test -d ~/projects/deep-code.bak` → 成功（バックアップ存在）
13. `grep -q "projects/deep-code" ~/.dotfiles/install.sh && echo OK` → OK
14. `cd ~/.dotfiles && git diff --stat --cached` → 空（全変更コミット済み）
15. `cd ~/.dotfiles && git status --short` → 本プラン対象外の既存変更（`git/.gitconfig`, `local-plugins/`, `user-plugins/`）のみが残ることを目視確認

## Rollback

全変更は git で追跡可能。

**全体ロールバック**:
- `rm ~/projects/deep-code` で symlink を削除
- `mv ~/projects/deep-code.bak ~/projects/deep-code` で元ディレクトリを復元
- `cd ~/.dotfiles && git revert <commit>...` で全コミット（US-011, US-012, US-013 part1, US-013 part2 の4件）を取り消し

**部分ロールバック**:
- US-011 のみ戻す: `git revert <US-011-commit>` — scripts tracking と _workspace/ cleanup のみ revert
- US-012 のみ戻す: `git revert <US-012-commit>` — SKILL.md 変更のみ revert
- US-013 のみ戻す: `git revert <US-013-commits...>` — deep-code 移行のみ revert + symlink 削除 + .bak から復元

## ADR

- **Decision**: stock-advisor scripts を dotfiles に直接追跡し、deep-code を dotfiles 内に移動して symlink + install.sh 更新で再現性を確保する（Option A x2）
- **Drivers**: 再現性、シンプルさ、既存 symlink パターンとの整合性
- **Alternatives considered**:
  - stock-advisor: 別リポジトリ + submodule（過剰のため棄却）
  - deep-code: 別リポジトリ維持（一元管理に反するため棄却）、git submodule（過剰設計のため棄却）
- **Why chosen**: dotfiles が唯一の source of truth となり、install.sh 一発で全 symlink が再現される。deep-code の symlink 先が dotfiles git リポジトリ内であることによる git 操作の混乱リスクは、deep-code が主に OMC によるファイル読み書きのみのプロジェクトメモであるため許容範囲。単一コミット履歴の喪失は、現状の deep-code の履歴価値が極小であるため受容
- **Consequences**: 
  - dotfiles リポジトリにプロジェクトメモが混在するが、runtime データ（`.omc/state/`, `.omc/sessions/`）は gitignore で除外される。`.omc/prd.json` と `.omc/progress.txt` は意図的に追跡する（プロジェクトの設計判断と進捗を記録する参照価値のある成果物であり、`state/` のような一時ランタイムデータではない）
  - `~/projects/deep-code/` での git 操作は dotfiles リポジトリの状態を表示する（ユーザーはこのパスで git 操作を行わない前提）
  - 新規マシンでは install.sh で deep-code symlink も自動作成される
- **Follow-ups**: dotfiles-omc-integration プランの実行（別セッションで対応）。pip install の自動化（requirements.txt の存在は install.sh 更新の契機として検討可能だが、現時点ではスコープ外）

## Changelog

- v4: Critic V2 レビュー反映
  - AC 9: grep パターンを word-boundary に修正（VS 9 と一致させる / Critic V2 MINOR-1）
  - Steps 2a/2b/3a/3b: stage 操作を先にまとめ commit を後に（番号の意味的順序を改善 / Critic V2 MINOR-2）
- v3: Architect V2 レビュー反映
  - Step 1b: `git rm --cached` → `git rm -r --cached` に修正（ディレクトリ再帰削除のため `-r` 必須 / Architect V2 Critical）
  - Step 5: rsync の trailing slash 注意書きを追加（Architect V2 Minor）
  - Step 0: `backup_and_link` 関数定義の事前確認ステップを追加（Architect V2 Minor）
  - AC 9: grep を `grep -Eq "(^|/)state($|/)"` に強化（word boundary / Architect V2 Minor）
  - US-011 と US-012 を別コミットに分割（Step 3a/3b）、部分ロールバックを実現（Architect V2 Minor）
  - ADR: prd.json/progress.txt の追跡理由を明記（Architect V2 Principle 3 clarification）
- v2: Architect V1 + Critic V1 レビュー反映
  - US-011: .gitignore に `logs/` を追加（Architect #1）
  - US-011: `_workspace/` を `git rm --cached` + .gitignore で除外（Critic MAJOR #3）
  - US-013: Step 5 を `rsync -av --exclude=.git` に具体化（Critic MAJOR #4）
  - US-013: Step 10 追加: `install.sh` に deep-code symlink 行を追加（Critic MAJOR #1）
  - US-014: AC 13 (バックアップ存在確認) 追加、AC 12 (_workspace 追跡除外) 追加、AC 9 を grep 検証に具体化（Critic MAJOR #2, MINOR #4）
  - VS 14: `git diff --stat --cached` に変更（ステージング確認）
  - VS 15: 新規追加 — 既存の他変更が残ることを明示（Critic MAJOR #2）
  - Rollback: 部分ロールバック手順を追加（Critic MINOR #3）
  - ADR: symlink-in-git-repo のトレードオフ、履歴喪失の受容、pip install のスコープ外判断を明記（Architect #1, Architect #4）
  - Risk: `_workspace/` リスクを具体化、symlink の git 混乱リスクを追加、pip install 手動実行のリスクを追加
  - Plans count 修正: 2→3（Critic MINOR #2）
- v1: Planner initial draft
