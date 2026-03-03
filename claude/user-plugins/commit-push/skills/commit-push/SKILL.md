---
name: commit-push
description: git の変更内容を分析してコミットメッセージを生成し、add → commit → push まで一括実行するスキル。「commitして」「pushして」「変更をコミット」「commit~push」「コミットしてプッシュ」「/commit-push」などのユーザーの発言で積極的に使用すること。git の変更をまとめてリモートに反映したい場面では必ずこのスキルを使うこと。
---

# commit-push スキル

git の変更を分析し、適切なコミットメッセージを提案してから add → commit → push を実行する。

## 手順

### 1. 変更内容を把握する

以下のコマンドで現在の状態を確認する：

```bash
git status
git diff HEAD
```

ステージ済みの変更がある場合は `git diff --cached` も確認する。

### 2. コミットメッセージを生成する

変更内容を分析し、**Conventional Commits 形式・日本語**でメッセージを作成する。

**フォーマット:**
```
<type>: <概要>

<本文（任意）>
```

**type の選択基準:**
| type | 用途 |
|------|------|
| `feat` | 新機能の追加 |
| `fix` | バグ修正 |
| `docs` | ドキュメントのみの変更 |
| `style` | コードの動作に影響しない変更（フォーマット等） |
| `refactor` | バグ修正でも機能追加でもないコード変更 |
| `test` | テストの追加・修正 |
| `chore` | ビルドプロセスや補助ツールの変更 |
| `delete` | ファイルや機能の削除 |

**メッセージ例:**
- `feat: ユーザー認証機能を追加`
- `fix: ログイン時のnullポインタエラーを修正`
- `docs: READMEにセットアップ手順を追記`
- `chore: 不要なphotosディレクトリを削除`

### 3. ユーザーに確認する

生成したコミットメッセージをユーザーに提示し、承認を得てから実行する。

提示例：
```
以下のコミットメッセージで進めます。よろしいですか？

  chore: 不要なphotosディレクトリを削除

[はい / 修正してください]
```

### 4. add → commit → push を実行する

承認を得たら以下を順に実行する：

```bash
# 変更をすべてステージ（未追跡ファイルを含む）
git add -A

# コミット（Co-Authored-By を付与）
git commit -m "$(cat <<'EOF'
<承認されたメッセージ>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"

# 現在のブランチをリモートへプッシュ
git push
```

### 5. 結果を報告する

push が成功したらコミットハッシュとブランチ名を簡潔に伝える。

## 注意事項

- `.env` や認証情報を含むファイルは絶対にコミットしない
- `main` / `master` への force push は絶対に行わない
- コンフリクトがある場合は解決してから進める
- push 先に upstream が設定されていない場合は `git push -u origin <branch>` を使う
