# JSON Output Schema

## Top-level
| Field | Type | Description |
|-------|------|-------------|
| fetched_at | string | ISO 8601 UTC |
| source | string | "SBI" |
| sync_status | string | ok, cache, auth_expired, network_error, parse_error, no_cookie, maintenance |
| cache_used | boolean | キャッシュ表示時は true |
| account | object | 口座情報 |
| holdings | array | 保有銘柄配列 |

## account
total_assets, available_cash, margin_ratio, buying_power, margin_principal, margin_collateral (all numbers)

## holdings[]
ticker, name, position_type, account_type, quantity, cost_price, current_price, margin_side?, open_date?, expiry_date?

`margin_side` は `position_type` が `信用` の場合に `買建` または `売建`。
