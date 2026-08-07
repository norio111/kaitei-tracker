"""
「令和８年度診療報酬改定について」（改定ハブページ）から
疑義解釈資料（およびその訂正）のリンクを抽出し、
revision_document(category='gigi') に保存する。

このページには疑義解釈以外にも告示・通知・薬価・訪問看護基準など
大量のリンクがあるが、今回は「疑義解釈」を含むリンクのみ対象にする。
（他カテゴリを拾いたくなったら、KEYWORDと正規表現を増やすだけで対応可能）
"""

import argparse
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import get_connection, upsert_documents  # noqa: E402
from common.wareki import extract_date  # noqa: E402

SOURCE_PAGE = "https://www.mhlw.go.jp/stf/newpage_67729.html"

# このキーワードを含むリンクテキストのみ対象にする
TARGET_KEYWORD = "疑義解釈"

# 訪問看護・在宅医療への言及があれば優先タグ（疑義解釈本文には出にくいが念のため）
PRIORITY_KEYWORDS = ["訪問看護", "在宅医療"]


def fetch_html(test_file: str | None) -> str:
    if test_file:
        with open(test_file, encoding="utf-8") as f:
            return f.read()
    res = requests.get(SOURCE_PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    return res.text


def parse_items(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for a in soup.select("a[href]"):
        title = a.get_text(strip=True)
        if TARGET_KEYWORD not in title:
            continue

        href = a.get("href", "")
        if not href.lower().endswith((".pdf", ".docx", ".xlsx")):
            continue
        if href.startswith("/"):
            href = "https://www.mhlw.go.jp" + href

        size_m = re.search(r"[\uFF3B\[]([\d.]+[KM]B)[\uFF3D\]]", title)
        size = size_m.group(1) if size_m else None

        # 「（そのN）」があれば連番として抽出（訂正版などは連番なしの場合もある）
        no_m = re.search(r"その(\d+)", title)
        item_no = no_m.group(1) if no_m else None

        is_priority = any(kw in title for kw in PRIORITY_KEYWORDS)

        items.append(
            {
                "title": title,
                "url": href,
                "size": size,
                "published_at": extract_date(title),
                "item_no": item_no,
                "is_priority": is_priority,
            }
        )
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-file", help="ローカルHTMLファイルでテストする場合のパス")
    args = parser.parse_args()

    html = fetch_html(args.test_file)
    items = parse_items(html)

    conn = get_connection()
    new_items = upsert_documents(conn, category="gigi", source_page=SOURCE_PAGE, items=items)

    print(f"[gigi] 取得件数: {len(items)}件 / 新規: {len(new_items)}件")
    for it in new_items:
        no_label = f"その{it['item_no']}" if it["item_no"] else "(番号なし/訂正)"
        print(f"  [{no_label}] {it['title']} 公開日:{it['published_at']}")
        print(f"    {it['url']}")

    conn.close()


if __name__ == "__main__":
    main()
