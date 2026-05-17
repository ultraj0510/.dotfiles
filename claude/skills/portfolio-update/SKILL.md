---
name: portfolio-update
description: 売買の記録、損益計算、保有銘柄の追加・削除
when_to_use: 「買った」「売った」「ポートフォリオ更新」「保有追加」または portfolio-update 明示呼出時
---

# portfolio-update — portfolio.yaml 更新

売買の記録とバリデーションを行う。現物/信用両対応。

## 手順

```bash
# 買い（現物）
~/.claude/skills/portfolio-update/scripts/update_portfolio buy <TICKER> <QTY> <PRICE> --type 現物

# 買い（信用）
~/.claude/skills/portfolio-update/scripts/update_portfolio buy <TICKER> <QTY> <PRICE> --type 信用 \
  --open-date 2026-05-17 --expiry-date 2026-11-17

# 売り
~/.claude/skills/portfolio-update/scripts/update_portfolio sell <TICKER> <QTY> <PRICE> --type 信用

# 保有確認
~/.claude/skills/portfolio-update/scripts/update_portfolio show
```

## バリデーションルール

- 売り数量が保有数量を超えていないか確認
- 信用建玉には `open_date`, `expiry_date` が必須
- 同一 ticker でも現物/信用で別エントリとして管理可能

## 現金残高の更新

`available_cash` は自動更新されないため、手動で `portfolio.yaml` を編集する。
