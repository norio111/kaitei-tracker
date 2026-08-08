"""
任意のキーワードに基づいて、revision_document / document_topic から
関連情報を集約しMarkdownレポートを生成する汎用スクリプト。

houmon_kango専用の generate_report.py と違い、こちらは特定分野向けの
LLM抽出フィールド（houmon_kango_related等）に依存せず、
change_points（本文からの構造化抽出結果）をキーワードで横断検索する。
そのため「リハビリ」「精神科」「歯科」等、今後どんなテーマでも
このスクリプトをそのまま使い回せる。

抽出元は2種類：
  ① Fact層：資料タイトル自体にキーワードを含むもの
  ② Interpretation層：change_points の point/quote にキーワードを含むもの
     （どの分野の資料であっても、本文中の言及を拾える）

使い方：
    python reports/generate_topic_report.py --keyword リハビリ
    python reports/generate_topic_report.py --keyword リハビリ --output reports/rehabili_report.md
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import DB_PATH  # noqa: E402

CATEGORY_LABELS = {
    "summary": "説明資料",
    "gigi": "疑義解釈",
}


def fetch_titled_documents(conn: sqlite3.Connection, keyword: str) -> list[dict]:
    """Fact層：タイトル自体にキーワードを含む資料"""
    rows = conn.execute(
        """
        SELECT category, title, url, published_at
        FROM revision_document
        WHERE title LIKE ? AND is_active = 1
        ORDER BY category, published_at
        """,
        (f"%{keyword}%",),
    ).fetchall()
    cols = ["category", "title", "url", "published_at"]
    return [dict(zip(cols, r)) for r in rows]


def fetch_change_point_mentions(conn: sqlite3.Connection, keyword: str) -> list[dict]:
    """Interpretation層：change_points中にキーワードを含む箇所を全document横断で検索"""
    rows = conn.execute(
        """
        SELECT rd.category, rd.title, rd.url, rd.published_at, dt.change_points
        FROM document_topic dt
        JOIN revision_document rd ON rd.id = dt.document_id
        WHERE rd.is_active = 1
        ORDER BY rd.category, rd.published_at
        """
    ).fetchall()

    results = []
    for category, title, url, published_at, cp_json in rows:
        try:
            change_points = json.loads(cp_json) if cp_json else []
        except json.JSONDecodeError:
            continue
        for cp in change_points:
            if not isinstance(cp, dict):
                continue
            text = f"{cp.get('point', '')} {cp.get('quote', '')}"
            if keyword in text:
                results.append(
                    {
                        "category": category,
                        "title": title,
                        "url": url,
                        "published_at": published_at,
                        "type": cp.get("type", ""),
                        "point": cp.get("point", ""),
                        "quote": cp.get("quote", ""),
                        "page": cp.get("page"),
                    }
                )
    return results


def render_markdown(keyword: str, titled_docs: list[dict], mentions: list[dict]) -> str:
    lines = []
    lines.append(f"# {keyword} 関連レポート")
    lines.append("")
    lines.append(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(
        f"令和８年度診療報酬改定の各種資料（説明資料・疑義解釈）から、"
        f"「{keyword}」に関連する情報を自動抽出したレポートです。"
    )
    lines.append("")

    lines.append(f"## ① タイトルに「{keyword}」を含む資料")
    lines.append("")
    if titled_docs:
        for d in titled_docs:
            cat_label = CATEGORY_LABELS.get(d["category"], d["category"])
            lines.append(f"- **[{cat_label}]** {d['title']}")
            lines.append(f"  - {d['url']}")
        lines.append("")
    else:
        lines.append("_該当資料なし_")
        lines.append("")

    lines.append(f"## ② 本文中で「{keyword}」に言及している変更点")
    lines.append("")
    if mentions:
        current_title = None
        for m in mentions:
            if m["title"] != current_title:
                current_title = m["title"]
                cat_label = CATEGORY_LABELS.get(m["category"], m["category"])
                lines.append(f"### [{cat_label}] {m['title']}")
                lines.append(f"{m['url']}")
                lines.append("")
            page_label = f"（page {m['page']}）" if m.get("page") else ""
            type_label = f"[{m['type']}] " if m.get("type") else ""
            lines.append(f"- {type_label}**{m['point']}** {page_label}")
            lines.append(f"  > {m['quote']}")
            lines.append("")
    else:
        lines.append("_該当箇所なし_")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True, help="検索キーワード（例: リハビリ）")
    parser.add_argument("--output", help="出力先。省略時は reports/<keyword>_report.md")
    args = parser.parse_args()

    output = args.output or f"reports/{args.keyword}_report.md"

    conn = sqlite3.connect(DB_PATH)

    titled_docs = fetch_titled_documents(conn, args.keyword)
    mentions = fetch_change_point_mentions(conn, args.keyword)

    markdown = render_markdown(args.keyword, titled_docs, mentions)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"レポート生成完了: {output}")
    print(f"  ① タイトル一致資料: {len(titled_docs)}件")
    print(f"  ② 本文中の言及: {len(mentions)}件")

    conn.close()


if __name__ == "__main__":
    main()
