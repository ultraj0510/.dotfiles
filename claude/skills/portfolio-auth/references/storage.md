# tokens.json Schema

## 保存先
`~/.config/sbi-portfolio/tokens.json` — 所有者のみ読み書き可能（0600）

## 構造
- `saved_at`: ISO 8601 (UTC)
- `source`: Cookieの取得経路 (check|env|stdin|file:<path>)
- `fingerprint`: 必須Cookie値の SHA256 先頭12桁（非秘密）
- `cookies`: Cookie-Editor JSON 互換の配列

## Legacy Paths
読み取り互換のみ。新規保存は canonical へ。

## 必須Cookie
JSESSIONID, __lt__sid, __lt__cid, AWSALBCORS
