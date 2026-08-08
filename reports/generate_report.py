"""
revision_document / document_topic から訪問看護・在宅医療関連の情報を集約し、
Markdownレポートを生成する。

抽出元は2種類：
  ① Fact層：説明資料のうち、タイトルに「訪問看護」「在宅医療」を含むもの
     （revision_document.is_priority=1）
     → 資料そのものが訪問看護をテーマにしている場合
  ② Interpretation層：疑義解釈等の本文中で訪問看護に言及している箇所
     （document_topic.houmon_kango_mentions）
     → 本題は別分野だが、Q&Aの中に訪問看護関連の記述がある場合

使い方：
    python reports/generate_report.py
    python reports/generate_report.py --output reports/houmon_kango_report.md
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


def fetch_priority_documents(conn: sqlite3.Connection) -> list[dict]:
    """Fact層：タイトル自体が訪問看護・在宅医療関連の資料"""
    rows = conn.execute(
        """
        SELECT category, title, url, published_at, size
        FROM revision_document
        WHERE is_priority = 1 AND is_active = 1
        ORDER BY category, published_at
        """
    ).fetchall()
    cols = ["category", "title", "url", "published_at", "size"]
    return [dict(zip(cols, r)) for r in rows]


def fetch_interpretation_mentions(conn: sqlite3.Connection) -> list[dict]:
    """Interpretation層：本文中に訪問看護への言及がある箇所"""
    rows = conn.execute(
        """
        SELECT rd.category, rd.title, rd.url, rd.published_at, dt.houmon_kango_excerpt
        FROM document_topic dt
        JOIN revision_document rd ON rd.id = dt.document_id
        WHERE dt.houmon_kango_related = 1
        ORDER BY rd.category, rd.published_at
        """
    ).fetchall()

    results = []
    for category, title, url, published_at, mentions_json in rows:
        try:
            mentions = json.loads(mentions_json) if mentions_json else []
        except json.JSONDecodeError:
            mentions = []
        # 旧形式（単一文字列）が残っている場合の後方互換
        if isinstance(mentions, str):
            mentions = [{"excerpt": mentions, "page": None}]

        for m in mentions:
            if not isinstance(m, dict):
                continue
            results.append(
                {
                    "category": category,
                    "title": title,
                    "url": url,
                    "published_at": published_at,
                    "excerpt": m.get("excerpt", ""),
                    "page": m.get("page"),
                }
            )
    return results


def fetch_priority_change_points(conn: sqlite3.Connection) -> list[dict]:
    """
    補足：houmon_kango_relatedにはフラグが立っていないが、
    change_points の point/quote 中に「訪問看護」の語が含まれるケースも拾っておく
    （抽出漏れの保険）。
    """
    rows = conn.execute(
        """
        SELECT rd.category, rd.title, rd.url, rd.published_at, dt.change_points
        FROM document_topic dt
        JOIN revision_document rd ON rd.id = dt.document_id
        WHERE dt.houmon_kango_related = 0
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
            if "訪問看護" in text:
                results.append(
                    {
                        "category": category,
                        "title": title,
                        "url": url,
                        "published_at": published_at,
                        "point": cp.get("point", ""),
                        "quote": cp.get("quote", ""),
                        "page": cp.get("page"),
                    }
                )
    return results


def render_markdown(priority_docs: list[dict], mentions: list[dict], bonus: list[dict]) -> str:
    lines = []
    lines.append("# 訪問看護・在宅医療 関連レポート")
    lines.append("")
    lines.append(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(
        "令和８年度診療報酬改定の各種資料（説明資料・疑義解釈）から、"
        "訪問看護・在宅医療に関連する情報を自動抽出したレポートです。"
    )
    lines.append("")

    # --- ① 資料そのものが訪問看護テーマの説明資料 ---
    lines.append("## ① 訪問看護・在宅医療そのものを扱う資料")
    lines.append("")
    if priority_docs:
        for d in priority_docs:
            cat_label = CATEGORY_LABELS.get(d["category"], d["category"])
            lines.append(f"- **[{cat_label}]** {d['title']}")
            lines.append(f"  - {d['url']}")
        lines.append("")
    else:
        lines.append("_該当資料なし_")
        lines.append("")

    # --- ② 疑義解釈等の本文中で訪問看護に言及している箇所 ---
    lines.append("## ② 他分野の資料中で訪問看護に言及している箇所")
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
            lines.append(f"> {m['excerpt']} {page_label}")
            lines.append("")
    else:
        lines.append("_該当箇所なし_")
        lines.append("")

    # --- ③ 抽出漏れの保険（houmon_kango_related=falseだが本文に語句が含まれるケース） ---
    if bonus:
        lines.append("## ③ 補足：houmon_kango_related=false だが「訪問看護」の語を含む箇所")
        lines.append("")
        lines.append(
            "_以下はLLMが「訪問看護への言及」と判定しなかったものの、"
            "念のため語句一致で拾った箇所です。誤検知・過検知を含む可能性があるため参考情報として扱ってください。_"
        )
        lines.append("")
        current_title = None
        for b in bonus:
            if b["title"] != current_title:
                current_title = b["title"]
                cat_label = CATEGORY_LABELS.get(b["category"], b["category"])
                lines.append(f"### [{cat_label}] {b['title']}")
                lines.append(f"{b['url']}")
                lines.append("")
            page_label = f"（page {b['page']}）" if b.get("page") else ""
            lines.append(f"- **{b['point']}** {page_label}")
            lines.append(f"  > {b['quote']}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/houmon_kango_report.md")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    priority_docs = fetch_priority_documents(conn)
    mentions = fetch_interpretation_mentions(conn)
    bonus = fetch_priority_change_points(conn)

    markdown = render_markdown(priority_docs, mentions, bonus)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"レポート生成完了: {args.output}")
    print(f"  ① 訪問看護テーマの資料: {len(priority_docs)}件")
    print(f"  ② 本文中の言及箇所: {len(mentions)}件")
    print(f"  ③ 補足（語句一致のみ）: {len(bonus)}件")

    conn.close()


if __name__ == "__main__":
    main()
