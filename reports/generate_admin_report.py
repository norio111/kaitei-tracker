"""
事務長プロファイル：病院全体の change_points を対象に、
「期限管理」と「収益インパクト」を軸に分類したレポートを作る。

設計方針：
  - リハビリ等、特定分野のキーワード絞り込みはしない
    （分野別の点数詳細はリハ管理者等の各部門責任者が見る前提。
     事務長は分野横断で経過措置の期限・点数変動を把握する立場）
  - 主軸は type。経過措置は届出期限が絡み対応の緊急度が高いため最優先。
    次に新設・廃止（収益構造そのものが変わる）、要件変更、
    最後に明確化・その他（収益への直接影響が薄い）の順とする
  - 各項目に「点数変動シグナル」（点/円/％や加算・減算等の語）を
    キーワードで機械検出し、シグナルありを各typeグループの先頭に出す
  - 経過措置については common/wareki.py で期限日を抽出し、
    期限が近い順に並べる（抽出できない場合は末尾）
  - document_topic のスキーマは変更しない。すべて表示層で完結する

使い方：
    python reports/generate_admin_report.py
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import DB_PATH  # noqa: E402
from reports.signals import extract_deadline, has_revenue_signal  # noqa: E402

CATEGORY_LABELS = {"summary": "説明資料", "gigi": "疑義解釈"}

# 経過措置を最優先（期限対応が必要）。新設・廃止は収益構造の変化、
# 要件変更はオペレーション変更、明確化・その他は最後に一括。
TYPE_PRIORITY_ORDER = ["経過措置", "新設", "廃止", "要件変更", "明確化", "その他"]


def fetch_all_change_points(conn: sqlite3.Connection) -> list[dict]:
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
            t = cp.get("type", "その他")
            if t not in TYPE_PRIORITY_ORDER:
                t = "その他"
            results.append(
                {
                    "category": category,
                    "title": title,
                    "url": url,
                    "type": t,
                    "point": cp.get("point", ""),
                    "quote": cp.get("quote", ""),
                    "page": cp.get("page"),
                    "revenue_signal": has_revenue_signal(text),
                    "deadline": extract_deadline(text) if t == "経過措置" else None,
                }
            )
    return results


def render_item(m: dict) -> list[str]:
    lines = []
    cat_label = CATEGORY_LABELS.get(m["category"], m["category"])
    page_label = f"（page {m['page']}）" if m.get("page") else ""
    signal_label = " 💰" if m["revenue_signal"] else ""
    deadline_label = f" ⏰期限: {m['deadline']}" if m.get("deadline") else ""
    lines.append(f"- [{cat_label}]{signal_label}{deadline_label} **{m['point']}** {page_label}")
    lines.append(f"  > {m['quote']}")
    lines.append(f"  - {m['title']}")
    lines.append(f"  - {m['url']}")
    lines.append("")
    return lines


def render_type_section(type_label: str, items: list[dict]) -> list[str]:
    if type_label == "経過措置":
        # 期限が近い順（Noneは末尾）に並べる
        items = sorted(items, key=lambda m: (m["deadline"] is None, m["deadline"] or ""))
        lines = [f"## {type_label}（{len(items)}件）", ""]
        for m in items:
            lines.extend(render_item(m))
        return lines

    lines = [f"## {type_label}（{len(items)}件）", ""]

    # それ以外：収益インパクトのシグナルがある項目を先に出す
    signal_items = [m for m in items if m["revenue_signal"]]
    other_items = [m for m in items if not m["revenue_signal"]]

    if signal_items:
        lines.append("#### 💰 点数・収益への影響が示唆される項目")
        lines.append("")
        for m in signal_items:
            lines.extend(render_item(m))

    if other_items:
        lines.append("#### その他")
        lines.append("")
        for m in other_items:
            lines.extend(render_item(m))

    return lines


def render_markdown(items: list[dict]) -> str:
    lines = []
    lines.append("# 令和８年度診療報酬改定 事務長向けレポート")
    lines.append("")
    lines.append(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(
        "病院全体の変更点（全分野）を対象にしています。分野別（リハビリ等）の"
        "算定要件の詳細は各部門責任者のレポートを参照してください。"
        "このレポートは「期限管理」と「収益インパクトの把握」に絞っています。"
    )
    lines.append("")
    lines.append(
        "表示順は「経過措置（期限が近い順）→ 新設 → 廃止 → 要件変更 → 明確化・その他」。"
        "💰は点数・金額・加算・減算等の語を含む項目（収益インパクトの可能性）、"
        "⏰は経過措置の期限を本文から自動抽出できた項目です。"
        "いずれも機械的なキーワード検出のため、抜け漏れ・誤検出があり得ます。"
    )
    lines.append("")

    for type_label in TYPE_PRIORITY_ORDER:
        type_items = [m for m in items if m["type"] == type_label]
        if not type_items:
            continue
        lines.extend(render_type_section(type_label, type_items))

    return "\n".join(lines)


def main():
    conn = sqlite3.connect(DB_PATH)
    items = fetch_all_change_points(conn)
    markdown = render_markdown(items)

    output = "reports/admin_report.md"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"レポート生成完了: {output}")
    print(f"  総件数: {len(items)}件")
    for type_label in TYPE_PRIORITY_ORDER:
        count = sum(1 for m in items if m["type"] == type_label)
        signal_count = sum(1 for m in items if m["type"] == type_label and m["revenue_signal"])
        print(f"    {type_label}: {count}件（うち収益シグナルあり: {signal_count}件）")

    conn.close()


if __name__ == "__main__":
    main()
