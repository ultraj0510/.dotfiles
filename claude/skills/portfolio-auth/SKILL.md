---
name: portfolio-auth
description: SBI証券セッションCookieの管理・状態検証・取得方法案内
when_to_use: 「SBIにログイン」「証券認証」「Cookie取得」または portfolio-auth 明示呼出時
---

# portfolio-auth — SBI証券 認証

SBI証券サイトのセッションCookieを管理し、有効性を検証する。

## 仕組み

- ユーザがブラウザでSBI証券に手動ログインし、Cookieを取得する
- 本スキルはCookieの有効性検証・状態表示・取得方法案内を行う
- Cookie-Editor JSON と `name=value; ...` 形式の両方を受け付ける
- 必須Cookie（JSESSIONID, __lt__sid, __lt__cid, AWSALBCORS）が欠けている場合は保存しない

## 保存済みCookieの検証

```bash
python3 ~/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py
```

- Cookie有効 → `STATUS: OK` と表示
- Cookie未設定 → `STATUS: UNSET` と表示
- Cookie切れ → `STATUS: EXPIRED` と表示、再取得を案内

## Fresh Cookie Handling

ユーザが新しいCookieを会話内で提供した場合、保存済みCookieを使わずに fresh input として扱う。
portfolio-fetch を実行する前に、必ずCookieを検証・保存すること。

### 環境変数経由（--save）

```bash
export SBI_COOKIE='<Cookie-Editor JSON>'
python3 ~/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py --save
```

### stdin経由（--save-stdin）

Cookie-Editor JSONをパイプまたは貼り付け:

```bash
python3 ~/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py --save-stdin
```

### ファイル経由（--save-file）

```bash
python3 ~/.dotfiles/claude/skills/portfolio-auth/auth_sbi.py --save-file /path/to/cookie.json
```

ファイルは所有者のみ読み取り可能（0600）であること。

### 注意

- **位置引数でCookieを渡さないでください。** `auth_sbi.py "<cookie>"` はエラーになります。
  `--save-stdin`, `--save-file`, または `SBI_COOKIE` 環境変数 + `--save` を使用してください。
- 成功時は `STATUS: OK` が出力され、`~/.config/sbi-portfolio/tokens.json` に保存されます。
- 保存されたCookieには source（env/stdin/file:path）と fingerprint（12桁の非秘密ハッシュ）が記録されます。
