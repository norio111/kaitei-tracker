"""
「令和８年度診療報酬改定説明資料等について」ページから
分野別の説明資料PDF一覧を取得し、revision_document(category='summary') に保存する。
"""

import argparse
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import get_connection, upsert_documents  # noqa: E402

SOURCE_PAGE = "https://www.mhlw.go.jp/stf/newpage_71068.html"
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
    for a in soup.select("a[href$='.pdf']"):
        href = a.get("href", "")
        if href.startswith("/"):
            href = "https://www.mhlw.go.jp" + href
        title = a.get_text(strip=True)

        m = re.match(r"\d+_(.+?)[\uFF3B\[]([\d.]+[KM]B)[\uFF3D\]]", title)
        if m:
            name, size = m.group(1).strip(), m.group(2)
        else:
            name, size = title, None

        is_priority = any(kw in name for kw in PRIORITY_KEYWORDS)

        items.append(
            {
                "title": name,
                "url": href,
                "size": size,
                "published_at": None,  # このページ自体には個別の公開日記載がないため保留
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
    new_items = upsert_documents(conn, category="summary", source_page=SOURCE_PAGE, items=items)

    print(f"[summary] 取得件数: {len(items)}件 / 新規: {len(new_items)}件")
    for it in new_items:
        tag = " 🔴訪問看護関連" if it["is_priority"] else ""
        print(f"  {it['title']} ({it['size']}){tag}\n    {it['url']}")

    conn.close()


if __name__ == "__main__":
    main()
