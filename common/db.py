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

    # Interpretation層：中身の解釈はここに保存する。
    # revision_document(Fact)は変更せず、こちらだけを再生成・更新していく。
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_topic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES revision_document(id),

            -- change_points: JSON配列。各要素は
            --   {"type": "新設|要件変更|明確化|経過措置|廃止|その他",
            --    "point": "本文に基づく1文要約",
            --    "quote": "本文からの逐語抜粋（要約・言い換え禁止）",
            --    "page": 抜粋元のページ番号(int)}
            -- type は分類判断＝Interpretationであり、quote/pageはFactへの参照。
            change_points TEXT NOT NULL,

            -- 「本文に訪問看護への言及が存在したか」という機械的事実
            -- （「影響があるか」というInterpretationの評価ではない）
            houmon_kango_related INTEGER NOT NULL,
            -- houmon_kango_excerpt: JSON配列。各要素は {"excerpt": "本文からの逐語抜粋", "page": ページ番号}
            -- change_pointsと同様、1箇所の連続した文章のみを許可し、複数箇所の結合は禁止する
            houmon_kango_excerpt TEXT,

            source_content_hash TEXT NOT NULL,  -- 生成時点のrevision_document.content_hash
            model_used TEXT NOT NULL,
            prompt_version TEXT NOT NULL,       -- 例: 'interpret-v0.1'
            generated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_topic_document_id ON document_topic(document_id)"
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


def get_pending_documents(
    conn: sqlite3.Connection, category: str | None = None, limit: int | None = None
) -> list[dict]:
    """
    まだInterpretationが無い、または元資料が差し替わって
    content_hashが変わった（＝再生成が必要な）revision_documentを返す。
    """
    query = """
        SELECT rd.id, rd.category, rd.title, rd.url, rd.content_hash, rd.is_priority
        FROM revision_document rd
        LEFT JOIN document_topic dt
            ON dt.document_id = rd.id AND dt.source_content_hash = rd.content_hash
        WHERE rd.is_active = 1 AND dt.id IS NULL
    """
    params: list = []
    if category:
        query += " AND rd.category = ?"
        params.append(category)
    query += " ORDER BY rd.is_priority DESC, rd.published_at DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cur = conn.execute(query, params)
    cols = ["id", "category", "title", "url", "content_hash", "is_priority"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_interpretation(
    conn: sqlite3.Connection,
    document_id: int,
    change_points_json: str,
    houmon_kango_related: bool,
    houmon_kango_excerpt: str,
    source_content_hash: str,
    model_used: str,
    prompt_version: str,
) -> None:
    conn.execute(
        """
        INSERT INTO document_topic
            (document_id, change_points, houmon_kango_related, houmon_kango_excerpt,
             source_content_hash, model_used, prompt_version, generated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            change_points_json,
            int(houmon_kango_related),
            houmon_kango_excerpt,
            source_content_hash,
            model_used,
            prompt_version,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()


def snapshot_revision_document(conn: sqlite3.Connection) -> tuple[int, str]:
    """
    revision_documentの件数と内容ハッシュを取る。
    Interpretation生成の前後でこれを比較し、Factテーブルが
    一切変更されていないことを機械的に確認するための保険。
    """
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(title) + LENGTH(url)), 0) FROM revision_document"
    ).fetchone()
    return row[0], str(row[1])
