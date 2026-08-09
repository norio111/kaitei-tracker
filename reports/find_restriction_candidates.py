"""
document_topic.change_points（point・quote）に対して、算定不可を示唆する
否定表現を含む候補を機械的に抽出し、目視確認用の一覧として出力する調査スクリプト。

【重要】これはrestrictionテーブルの実装ではない。
    「肯定条件（requirement）は既にchange_pointsに現れているが、
     否定条件（算定できない理由）を表現する場所が今のスキーマに無い」
    という仮説を検証するための、DBを一切変更しない監査ツール。

    ここでの目的は「正確な自動分類」ではなく「穴の形を知ること」。
    キーワード一致は広めに取り、過検知（本当はrestrictionでないもの）が
    混ざる前提で、人間が実例を読んで判断する。

対象はリハビリ等の分野に絞らず、document_topic全体（is_active=1）とする。
特定分野に絞ると、その分野特有の言い回しの癖に引っ張られる可能性があるため。

使い方：
    python reports/find_restriction_candidates.py
    python reports/find_restriction_candidates.py --limit 30
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import DB_PATH  # noqa: E402

CATEGORY_LABELS = {"summary": "説明資料", "gigi": "疑義解釈"}

# 広めに取る。過検知は許容し、人間が読んで判断する前提。
NEGATION_KEYWORDS = [
    "算定できない",
    "算定不可",
    "算定することはできない",
    "算定できないものとする",
    "対象外",
    "算定対象外",
    "含まない",
    "該当しない",
    "認められない",
    "算定しない",
    "算定されない",
    "できないものとする",
    "算定不能",
]

NEGATION_PATTERN = re.compile("|".join(re.escape(kw) for kw in NEGATION_KEYWORDS))


def fetch_candidates(conn: sqlite3.Connection) -> list[dict]:
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
            point = cp.get("point", "")
            quote = cp.get("quote", "")
            text = f"{point} {quote}"
            matches = sorted(set(NEGATION_PATTERN.findall(text)))
            if not matches:
                continue
            results.append(
                {
                    "category": category,
                    "title": title,
                    "url": url,
                    "published_at": published_at,
                    "type": cp.get("type", ""),
                    "point": point,
                    "quote": quote,
                    "page": cp.get("page"),
                    "matched_keywords": matches,
                }
            )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="表示件数の上限（既定は全件）")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    candidates = fetch_candidates(conn)
    conn.close()

    print(f"restriction候補: {len(candidates)}件\n")

    # キーワード別の出現頻度（複数該当は重複カウント）
    keyword_counts: dict[str, int] = {}
    for c in candidates:
        for kw in c["matched_keywords"]:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    print("キーワード別内訳:")
    for kw, count in sorted(keyword_counts.items(), key=lambda x: -x[1]):
        print(f"  {kw}: {count}件")
    print()

    # type別の内訳（restrictionがどのtypeに偏って現れるかを見る）
    type_counts: dict[str, int] = {}
    for c in candidates:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1
    print("type別内訳:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}件")
    print()

    shown = candidates[: args.limit] if args.limit else candidates
    print(f"--- 候補一覧（{len(shown)}/{len(candidates)}件を表示） ---\n")
    for i, c in enumerate(shown, 1):
        cat_label = CATEGORY_LABELS.get(c["category"], c["category"])
        page_label = f"（page {c['page']}）" if c.get("page") else ""
        print(f"[候補{i}] type={c['type']} 一致語={c['matched_keywords']}")
        print(f"  point: {c['point']}")
        print(f"  quote: {c['quote']} {page_label}")
        print(f"  出典: [{cat_label}] {c['title']}")
        print()


if __name__ == "__main__":
    main()
