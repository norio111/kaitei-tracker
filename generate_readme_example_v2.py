"""
kaitei-tracker の document_topic テーブルから実際のレコードを1件抜き出し、
README に貼れる Before/After 形式の Markdown を自動生成する（v2: change_points整形版）。

使い方（Windows側で、kaitei-trackerフォルダ直下から）:
    python generate_readme_example.py
"""

import sqlite3
import os
import sys
import json

CANDIDATES = ["db/kaitei.db", "db/kaitei_fact.db", "kaitei.db", "kaitei_fact.db"]


def find_db():
    for path in CANDIDATES:
        if os.path.exists(path):
            return path
    print("DBファイルが見つかりませんでした。")
    sys.exit(1)


def get_table_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def main():
    db_path = find_db()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM document_topic")
    total = cur.fetchone()[0]

    # houmon_kango_related=1 かつ change_points が充実してるものを優先して1件抜く
    cur.execute("""SELECT dt.id, dt.document_id, dt.change_points, dt.houmon_kango_related,
                           dt.houmon_kango_excerpt, dt.source_content_hash, dt.model_used,
                           dt.prompt_version, dt.generated_at,
                           rd.title, rd.url, rd.category, rd.published_at
                    FROM document_topic dt
                    JOIN revision_document rd ON rd.id = dt.document_id
                    WHERE dt.change_points IS NOT NULL AND dt.change_points != '[]'
                    ORDER BY LENGTH(dt.change_points) DESC
                    LIMIT 1""")
    row = cur.fetchone()
    conn.close()

    if row is None:
        print("該当レコードが見つかりませんでした。")
        sys.exit(1)

    (topic_id, document_id, change_points_raw, houmon_related, houmon_excerpt,
     content_hash, model_used, prompt_version, generated_at,
     title, url, category, published_at) = row

    try:
        change_points = json.loads(change_points_raw)
    except (json.JSONDecodeError, TypeError):
        change_points = None

    lines = []
    lines.append("## 実例：診療報酬改定資料からのFact/Interpretation抽出\n")
    lines.append(f"（`db/kaitei.db` の `document_topic` テーブルより実データを抜粋。"
                 f"現在 {total} 件を処理済み）\n")

    lines.append("### 入力（Fact層 / `revision_document`）\n")
    lines.append(f"- **タイトル**：{title}")
    lines.append(f"- **カテゴリ**：{category}")
    lines.append(f"- **公表日**：{published_at}")
    lines.append(f"- **URL**：{url}\n")

    lines.append("### 出力（Interpretation層 / `document_topic`）\n")

    if change_points:
        shown = change_points[:2]
        for i, cp in enumerate(shown, 1):
            lines.append(f"**変更点 {i}**")
            lines.append(f"- type: `{cp.get('type', '(不明)')}`")
            lines.append(f"- point: {cp.get('point', '(なし)')}")
            if cp.get("quote"):
                lines.append(f"- quote（原文逐語抜粋）: > {cp['quote']}")
            if cp.get("page"):
                lines.append(f"- page: {cp['page']}")
            lines.append("")
        if len(change_points) > 2:
            lines.append(f"（この資料からは全{len(change_points)}件の変更点を抽出。"
                         f"全件は `db/kaitei.db` の `document_topic` テーブル、"
                         f"またはレポート出力（`reports/`）を参照）\n")

    if houmon_related and houmon_excerpt:
        try:
            houmon_parsed = json.loads(houmon_excerpt)
        except (json.JSONDecodeError, TypeError):
            houmon_parsed = None

        lines.append("**訪問看護関連の抽出**\n")
        if houmon_parsed and isinstance(houmon_parsed, list):
            for item in houmon_parsed:
                excerpt = item.get("excerpt", "")
                page = item.get("page", "")
                lines.append(f"> {excerpt}")
                if page:
                    lines.append(f">\n> （page {page}）")
                lines.append("")
        else:
            lines.append(f"> {houmon_excerpt}\n")

    lines.append("### この抽出の再現性（provenance）\n")
    lines.append("| 項目 | 値 |")
    lines.append("|---|---|")
    lines.append(f"| topic_id | {topic_id} |")
    lines.append(f"| 使用モデル | `{model_used}` |")
    lines.append(f"| プロンプトバージョン | `{prompt_version}` |")
    lines.append(f"| 元資料ハッシュ | `{content_hash}` |")
    lines.append(f"| 生成日時 | {generated_at} |")
    lines.append("")
    lines.append("quoteは元資料本文と自動照合済み（NFKC正規化・クロスページマッチング）。"
                  "元資料が改訂された場合はcontent_hashの差分で検知できる設計。\n")

    lines.append(f"出典：厚生労働省ホームページ「{title}」（{url}）をもとに（作成者名）が構造化・加工")
    lines.append("<!-- (作成者名)の部分を、あなたの氏名または屋号に置き換えてください -->")

    out = "\n".join(lines)
    with open("readme_example.md", "w", encoding="utf-8") as f:
        f.write(out)

    print(out)
    print("\n\nreadme_example.md に出力しました。")


if __name__ == "__main__":
    main()