# Lessons

Shared lessons for Codex and Claude Code work in `/Users/fujie/code`.

Tool-specific lessons may point here instead of duplicating content.

## 2026-05-29

### SBI auth: JSESSIONID domain matters
- SBI JSESSIONID is hostOnly for `site1.sbisec.co.jp`. Using `www.sbisec.co.jp` URLs causes cookies to never be sent.
- Fix: all SBI page access URLs must use `site1.sbisec.co.jp`.

### Report generation: same-ticker multi-position handling
- portfolio.yaml can have multiple positions for the same ticker (現物×N, 信用×N).
- Never use `dict[ticker] = position` for lookups — use list iteration.
- Verify position count matches between portfolio.yaml and report before claiming completion.

### Cookie store: semicolon splitting
- Raw cookie strings use `; ` (semicolon-space) as separator, not just `;`.
- `read_cookie_objects()` must handle both raw cookie strings and JSON arrays.

## 2026-06-10

### スピーチ原稿作成: スライドに書かれていないことを足さない
- スライドの内容をスピーチ原稿に展開する際、スライドにない繋がり・解釈・展望を創作してはいけない。
- 特にやりがちな失敗:
  1. スライドの項目数を間違える（4項目を3つにまとめる等）
  2. スライドのニュアンスを逆に読む（「残り10%は人手必須」を「残り10%も自動化進行中」と書く等）
  3. スライドにない関連性を創作する（「KDGの技術を応用」等）
  4. スライドと全く違う内容を書く（図表中心のスライドを読み取れず、架空の展望を書く等）
- スライドの内容が図中心でテキスト抽出が不十分な場合は、グループ図形を再帰的に探索する。それでも不明ならユーザーに確認する。

## 2026-06-19

### stock-info-fetch: URL構築は実画面確認が必須
- 計画段階では推定URLで進めがちだが、SBI証券のように独自フレームワーク（`WPLETsiR001Idtl10`等）を使うサイトでは、推定値で1ページも到達できない。
- `_ActionID=DTLS` のような単純な推測値はほぼ当たらない。実画面でURLを確認し、`stock_sec_code_mul` のような実際のパラメータ名を使う。
- 設計段階で調査済みURLをfixture化し、`build_detail_url()` のテストから書く。

### stock-info-fetch: 外部ホストへのCookie送信は送信前に防ぐ
- `graph.sbisec.co.jp`、`sbi.ifis.co.jp`、`app.stockreportsplus.com` はSBI傘下だがCookieを送信してはいけない。
- `login.sbisec.co.jp` へのリダイレクトは認証切れとして検出し、`unexpected_host` と区別する。
- リダイレクト先ホストをチェックするコードはHTTPクライアントとredirect handlerの両方に必要（handlerはHTTP-level redirect、response.urlはトランスポートレベルの最終URL）。

### stock-info-fetch: パーサーのsource_changedは出力スキーマでerrorに正規化する
- パーサー内部では `source_changed` のような詳細ステータスを使うが、最終JSONのsection.statusは仕様上の3値（ok/not_available/error）のみ。
- オーケストレータ側で `source_changed` → `error` の正規化を一元化し、全セクションに適用する。

### stock-info-fetch: パーサーの最低抽出閾値を設定する
- 6項目中1項目だけ取れても成功扱いすると、画面変更を検出できない。
- 企業スコアは最低3/6項目、PDFは最低2/6カテゴリの充足を必須とする。
- 四季報の記事ブロック見出し（【連続増配】等）は銘柄ごとに変わるため、DOM順やブロック位置から動的に抽出する。

### stock-info-fetch: 計画の全Stepに具体的コマンドと期待結果を書く
- writing-plans に従い、Step 2/4 にも必ず具体的な `cd` と `pytest` コマンドと期待FAIL/PASSを書く。
- 実接続スモークテストはファイル作成タスクを計画に含め、skip markerで通常実行から分離する。
- requirements.txt にテスト用ライブラリ（reportlab）を含め、環境依存フォントを避ける。

### stock-info-fetch: auth_expiredチェックは全Cookie付き取得経路に必要
- 最初の直接タブだけにauth_expiredチェックを入れても、分析タブ・業績ポップアップ・適時開示ポップアップで認証切れになると部分エラー扱いでキャッシュされる。
- Cookieを送信するすべての `fetch_html` 呼び出しで `auth_expired` をチェックし、即座に全体エラーを返す。

### stock-info-fetch: パーサー出力のerror詳細はerrors配列へ伝播させる
- `_set_section` のような正規化関数が `source_changed` → `error` だけを処理していると、PDFパーサー等が返す `status=error` + `error_code` + `message` が失われる。
- 全パーサーの `error` ステータスを `errors` 配列へ追加する汎用的なパスを正規化関数に持たせる。

### stock-info-fetch: 上流取得失敗を「不存在」扱いしない
- スコアiframeの取得失敗時に `score_html` が空になり、PDF抽出が行われず `not_available` になるのは誤り。
- 上流の取得失敗と実際の不存在を区別する。取得失敗なら `error`、ソースURLが存在しない場合のみ `not_available` とする。

### stock-info-fetch: 数値抽出カウントは実際の数値取得数で判定する
- 業績行の認識だけでは不十分。全4期間が `--` でも `extracted += 1` される。
- 行の少なくとも1つの値が `None` でないことを確認してからカウントする。

### stock-info-fetch: 未知の行種別は成功扱いせず検出する
- 数値があれば `extracted` を増やす実装では、「市場予想」のような未知種別が全配列空の `status=ok` を生む。
- `extracted += 1` は既知種別のif/elif分岐の中だけに置き、未知種別は通過させない。

### stock-info-fetch: 構造要素の不在をデータ不存在と誤判定しない
- iframe抽出失敗を `not_available` にすると、画面構造変更でも「対象情報が存在しない」と誤ってキャッシュされる。
- 明示的な「○○はありません」テキストを確認できた場合だけ `not_available`、それ以外の構造的欠落は `source_changed` → `error` とする。
