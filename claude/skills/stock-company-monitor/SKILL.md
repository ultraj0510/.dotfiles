---
name: stock-company-monitor
description: Weekday monitoring of registered tickers for major IR events with auto re-analysis
---

# stock-company-monitor

平日に登録銘柄の重大IRイベントを監視し、旧レーティングを失効させ、自動再分析を行う。

## 呼び出し

stock-company-monitor run [--auto-reanalyze] [--data-dir PATH]
stock-company-monitor add <ticker>
stock-company-monitor remove <ticker>
stock-company-monitor list
