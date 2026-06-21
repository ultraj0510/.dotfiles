"""Synthetic HTML fixtures for index and document tests."""

TABLE_HTML = """
<html><body>
<table>
<tr><td>2026年5月10日</td><td><a href="/ir/pdf/results.pdf">2026年3月期 決算短信</a></td></tr>
<tr><td>2026/05/10</td><td><a href="/ir/docs/2026/05/presentation.pdf">決算説明資料</a></td></tr>
</table>
</body></html>
"""

CARD_HTML = """
<html><body>
<section><h3>2025年3月期</h3>
<article><time>2025.05.12</time><a href="/docs/presentation.pdf">決算説明資料</a></article>
</section>
</body></html>
"""

ARCHIVE_HTML = """
<html><body>
<a href="/ir/library/">IRライブラリー</a>
<a href="/ir/library/archive.html">過去の決算資料</a>
</body></html>
"""

JS_ONLY_HTML = """
<html><body>
<div id="ir-library"></div>
<script src="/assets/ir.js"></script>
</body></html>
"""

EXT_LINK_HTML = """
<html><body>
<a href="https://cdn.example.net/ir/results.pdf">決算短信</a>
</body></html>
"""

PAGINATION_HTML = """
<html><body>
<table>
<tr><td>2026年5月10日</td><td><a href="/ir/results1.pdf">短信1</a></td></tr>
</table>
<a href="/ir/?page=2">次へ</a>
</body></html>
"""
