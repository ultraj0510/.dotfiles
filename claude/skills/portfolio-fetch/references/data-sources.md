# SBI Data Sources

## Portfolio Page
- URL: site1.sbisec.co.jp/ETGate/ (WPLETpfR001Control)
- Encoding: cp932
- UA primary: iPhone Safari (mobile), fallback: Windows Chrome (desktop)

## Account Page
- URL: site1.sbisec.co.jp/ETGate/ (WPLETacR001Control)
- Encoding: cp932
- Note: 失敗時はWARNをstderrに出力し続行

## Ticker Mapping
SBI_TICKER_MAP: 7 static entries (ＮＦ金価格→1328.T, 日鉄鉱→1515.T, etc.)
Unmapped: XXXX.T from SBI 4-digit code.

## Cookie
read_cookie_bundle() from ~/.config/sbi-portfolio/tokens.json (managed by portfolio-auth)
