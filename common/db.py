"""
revision_document テーブルへの共通アクセス層。

設計方針：
  - ここに保存するのは Fact のみ（URL・タイトル・公開日・検知日時など）。
  - 「重要かどうか」「何が変わったか」といった Interpretation は
    別レイヤー（document_topic 等、将来追加）で扱う。
  - category で種別を分けることで、疑義解釈以外（通知・薬価・訪問看護等）を
    同じテーブル・同じロジックで扱えるようにする。
"""

import hashlib
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "kaitei.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS revision_document (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,       -- 'summary' / 'gigi' / 'notification' / 'yakka' ...
            title TEXT NOT NULL,
            published_at TEXT,            -- 資料自体に記載の日付（分かる場合）YYYY-MM-DD
            url TEXT UNIQUE NOT NULL,
            source_page TEXT,             -- どのハブページから拾ったか
            size TEXT,
            content_hash TEXT,            -- 将来、内容差分検知に使う余地を残す
            is_priority INTEGER DEFAULT 0,-- 訪問看護・在宅医療関連フラグ
            fetched_at TEXT NOT NULL,     -- このツールが検知した日時
            is_active INTEGER DEFAULT 1   -- 元ページから消えたら0（削除はしない）
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_revision_document_category ON revision_document(category)"
    )
    conn.commit()


def make_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def upsert_documents(conn: sqlite3.Connection, category: str, source_page: str, items: list[dict]) -> list[dict]:
    """
    items: [{title, url, published_at, size, is_priority}, ...]
    戻り値：新規に追加された items
    """
    now = datetime.now().isoformat()
    new_items = []
    seen_urls = set()

    for it in items:
        seen_urls.add(it["url"])
        cur = conn.execute("SELECT id FROM revision_document WHERE url=?", (it["url"],))
        if cur.fetchone() is None:
            content_hash = make_hash(it["url"], it["title"])
            conn.execute(
                """
                INSERT INTO revision_document
                    (category, title, published_at, url, source_page, size,
                     content_hash, is_priority, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    it["title"],
                    it.get("published_at"),
                    it["url"],
                    source_page,
                    it.get("size"),
                    content_hash,
                    int(it.get("is_priority", False)),
                    now,
                ),
            )
            new_items.append(it)

    # 同じcategory・source_page内で、今回のスクレイピングに出てこなかったURLは非アクティブ化
    cur = conn.execute(
        "SELECT id, url FROM revision_document WHERE category=? AND source_page=? AND is_active=1",
        (category, source_page),
    )
    for row_id, url in cur.fetchall():
        if url not in seen_urls:
            conn.execute("UPDATE revision_document SET is_active=0 WHERE id=?", (row_id,))

    conn.commit()
    return new_items
