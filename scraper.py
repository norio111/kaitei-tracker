import argparse
import os
import re
import sqlite3
from datetime import datetime

import requests
from bs4 import BeautifulSoup

URL = "https://www.mhlw.go.jp/stf/newpage_71068.html"
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "kaitei_fact.db")

# 訪問看護・在宅医療関連は優先タグを付ける（eWell案件との関連チェック用）
PRIORITY_KEYWORDS = ["訪問看護", "在宅医療"]


def fetch_html(test_file: str | None) -> str:
    if test_file:
        with open(test_file, encoding="utf-8") as f:
            return f.read()
    res = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
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

        m = re.match(r"(\d+)_(.+?)[\uFF3B\[]([\d.]+[KM]B)[\uFF3D\]]", title)
        if m:
            no, name, size = m.group(1), m.group(2).strip(), m.group(3)
        else:
            no, name, size = None, title, None

        is_priority = any(kw in name for kw in PRIORITY_KEYWORDS)

        items.append(
            {
                "no": no,
                "name": name,
                "url": href,
                "size": size,
                "priority": is_priority,
            }
        )
    return items


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kaitei_fact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_no TEXT,
            item_name TEXT,
            url TEXT UNIQUE,
            size TEXT,
            is_priority INTEGER DEFAULT 0,
            first_seen_at TEXT,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    conn.commit()


def sync(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    now = datetime.now().isoformat()
    new_items = []
    seen_urls = set()

    for it in items:
        seen_urls.add(it["url"])
        cur = conn.execute("SELECT id FROM kaitei_fact WHERE url=?", (it["url"],))
        if cur.fetchone() is None:
            conn.execute(
                """
                INSERT INTO kaitei_fact
                    (item_no, item_name, url, size, is_priority, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (it["no"], it["name"], it["url"], it["size"], int(it["priority"]), now),
            )
            new_items.append(it)

    # ページから消えた項目は非アクティブ化（削除はしない = Factは残す）
    cur = conn.execute("SELECT id, url FROM kaitei_fact WHERE is_active=1")
    for row_id, url in cur.fetchall():
        if url not in seen_urls:
            conn.execute("UPDATE kaitei_fact SET is_active=0 WHERE id=?", (row_id,))

    conn.commit()
    return new_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-file", help="ローカルHTMLファイルでテストする場合のパス")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    html = fetch_html(args.test_file)
    items = parse_items(html)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    new_items = sync(conn, items)

    print(f"取得件数: {len(items)}件 / 新規: {len(new_items)}件")
    if new_items:
        print("::notice::新規/更新資料を検出")
        for it in new_items:
            tag = " 🔴訪問看護関連" if it["priority"] else ""
            print(f"  [{it['no']}] {it['name']} ({it['size']}){tag}")
            print(f"      {it['url']}")

    # 優先項目のサマリも常に出す
    priority_rows = conn.execute(
        "SELECT item_no, item_name, url FROM kaitei_fact WHERE is_priority=1 AND is_active=1"
    ).fetchall()
    if priority_rows:
        print("\n--- 訪問看護・在宅医療 関連資料（現在有効） ---")
        for no, name, url in priority_rows:
            print(f"  [{no}] {name}\n      {url}")

    conn.close()


if __name__ == "__main__":
    main()
