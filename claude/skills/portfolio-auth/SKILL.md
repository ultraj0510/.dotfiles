---
name: portfolio-auth
description: SBI証券セッションCookieの管理・状態検証・取得方法案内
when_to_use: 「SBIにログイン」「証券認証」「Cookie取得」または portfolio-auth 明示呼出時
---

# portfolio-auth — SBI証券 認証

SBI証券サイトのセッションCookieを管理し、有効性を検証する。

## 仕組み

- ユーザがブラウザでSBI証券に手動ログインし、Cookieを取得して `SBI_COOKIE` 環境変数に設定する
- 本スキルはCookieの有効性検証・状態表示・取得方法案内を行う
- Cookie-Editor JSON と `name=value; ...` 形式の両方を受け付ける
- 必須Cookieが欠けている場合は保存しない

## Cookie取得方法

1. ブラウザで https://www.sbisec.co.jp/ にログイン
2. ログイン後、Cookie-Editor 拡張機能でCookieをエクスポート
3. エクスポートした文字列を環境変数に設定:

```bash
export SBI_COOKIE="JSESSIONID=xxx; ..."
```

## 検証

```bash
cd ~/.claude/skills/portfolio-auth
python3 auth_sbi.py
```

- Cookie有効 → `OK` と表示
- Cookie切れ → `EXPIRED` と表示、再取得を案内
