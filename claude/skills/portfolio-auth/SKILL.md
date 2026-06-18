---
name: portfolio-auth
description: Use when SBI証券のセッションCookieを検証・保存・状態確認する。Cookie切れ時の再取得案内を含む。
---

# portfolio-auth — SBI証券 認証

SBI証券サイトのセッションCookieを管理し、有効性を検証する。`portfolio-fetch` 実行前の前提認証を担う。

## 適用範囲

- SBI証券にログイン済みのブラウザからCookieを取得し、検証・保存する
- 保存済みCookieの有効性を確認する
- Cookieが未設定・期限切れの場合、再取得方法を案内する

**非適用:** テクニカル分析、保有銘柄の取得（`portfolio-fetch` を使用）。

## コマンド

```bash
cd ~/.agents/skills/portfolio-auth

# 保存済みCookieの有効性検証・状態表示
python3 auth_sbi.py

# SBI_COOKIE環境変数からCookieを検証→保存
python3 auth_sbi.py --save

# stdinからCookieを検証→保存
python3 auth_sbi.py --save-stdin

# 0600権限のファイルからCookieを検証→保存
python3 auth_sbi.py --save-file /path/to/cookie.json
```

## データ保存先

`~/.config/sbi-portfolio/tokens.json` — canonical。スキーマ詳細は `references/storage.md` 参照。

## Gotchas

- **import 時 execv:** `auth_sbi.py` は Playwright 不在時に venv 再実行する。この判定は `if __name__ == "__main__"` 配下にあり、pytest 等の import では発動しない。
- **必須Cookie欠損:** `JSESSIONID`, `__lt__sid`, `__lt__cid`, `AWSALBCORS` のいずれかが欠けたCookieは保存を拒否する。
- **Playwright不在:** システムの python3 に Playwright がない場合、`~/.dotfiles/claude/skills/portfolio-auth/.venv/bin/python` で再実行を試みる。

## 完了証拠

- 検証成功: `STATUS: OK` + exit 0 + `tokens.json` の `saved_at` 更新
- 未設定: `STATUS: UNSET` + exit 1
- 期限切れ: `STATUS: EXPIRED` + exit 1 + 再取得手順表示
