"""
リハビリ関連の change_points を「病棟・算定区分」を主軸に、
「疾患別」「テーマ」を副軸として分類し、階層的なMarkdownレポートを作る。

このスクリプトは「リハ管理者」自身が、さらに2種類の読者に向けて
発信するための2モードを持つ：

  --audience staff（既定）：リハ職員向け運用連絡
      type全種（明確化含む）。病棟軸→テーマ軸の階層構造で現場業務を網羅する。

  --audience admin：事務長向け報告
      type ∈ {新設, 廃止, 要件変更, 経過措置} のみに絞る（明確化＝運用解釈の
      確認は現場向けであり、事務長が見るべき「収益構造・届出の変化」ではないため）。
      診療報酬改定の話題は「点」「加算」等の語がほぼ全項目に出現し、
      キーワードによる収益シグナル検出（💰）は識別力を持たないと分かったため、
      このモードでは💰は使わず、type分類そのもので絞り込む。
      経過措置には引き続き期限（⏰）を表示する。

設計方針：
  - document_topic のスキーマは変更しない（Factは変えず、見せ方だけ再生成する）
  - 分類はキーワードによる機械的な仕分けであり、LLMには一切通さない
    （コストゼロ・再現性あり・後からルールを直せば再生成し放題）

使い方：
    python reports/generate_rehabili_hierarchy.py --audience staff
    python reports/generate_rehabili_hierarchy.py --audience admin
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import DB_PATH  # noqa: E402
from reports.signals import extract_deadline, is_calculation_decision  # noqa: E402

CATEGORY_LABELS = {"summary": "説明資料", "gigi": "疑義解釈"}

KEYWORD = "リハビリ"

# 事務長向けで残すtype（収益構造・届出の変化に直結するもの）
ADMIN_RELEVANT_TYPES = {"新設", "廃止", "要件変更", "経過措置"}


def is_admin_relevant(m: dict) -> bool:
    """
    事務長向けに残すべき項目かどうかを判定する。
    typeが収益構造に直結するもの（新設・廃止・要件変更・経過措置）に加え、
    typeが「明確化」であっても、算定可否そのものへの言及がある場合は
    実質的に収益・事務判断に直結するため対象に含める
    （「明確化」という体裁の中に「算定できる/できない」の答えそのものが
      紛れているケースが実データで確認されたため）。
    """
    if m["type"] in ADMIN_RELEVANT_TYPES:
        return True
    text = f"{m['point']} {m['quote']}"
    return m["type"] == "明確化" and is_calculation_decision(text)

# 軸①：病棟・算定区分（主軸。この順序でセクションを出す）
WARD_AXIS = [
    ("回復期", ["回復期リハビリテーション病棟", "回復期リハビリテーション入院医療管理料"]),
    ("地域包括医療病棟", ["地域包括医療病棟"]),
    ("地域包括ケア病棟", ["地域包括ケア病棟"]),
    ("急性期", ["急性期一般入院料", "急性期病院一般入院基本料", "特定機能病院入院基本料", "特定集中治療室"]),
    ("療養病棟", ["療養病棟"]),
    ("外来・在宅", ["外来", "訪問リハビリテーション", "退院前訪問指導料", "通所リハビリテーション"]),
]

# 軸②：疾患別
DISEASE_AXIS = [
    ("脳血管疾患等", ["脳血管疾患等リハビリテーション", "高次脳機能障害"]),
    ("運動器", ["運動器リハビリテーション"]),
    ("廃用症候群", ["廃用症候群リハビリテーション"]),
    ("がん患者", ["がん患者リハビリテーション"]),
    ("摂食嚥下", ["摂食嚥下"]),
    ("心大血管疾患", ["心大血管疾患リハビリテーション"]),
]

# 軸③：テーマ（介入形態・事務手続き）
THEME_AXIS = [
    ("離床・ベッド上", ["離床を伴わず", "ベッド上", "ポジショニング", "拘縮"]),
    ("計画書・記録", ["実施計画書", "総合実施計画書", "総合計画評価料", "署名"]),
    ("多職種・研修", ["研修", "看護師、理学療法士", "多職種"]),
    ("点数・算定要件", ["点", "加算", "算定"]),
    ("経過措置", ["経過措置", "当分の間", "令和８年度中"]),
]


def classify(text: str, axis: list[tuple[str, list[str]]]) -> list[str]:
    return [label for label, keywords in axis if any(kw in text for kw in keywords)]


def fetch_mentions(conn: sqlite3.Connection, keyword: str) -> list[dict]:
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
            if keyword not in text:
                continue
            results.append(
                {
                    "category": category,
                    "title": title,
                    "url": url,
                    "type": cp.get("type", ""),
                    "point": cp.get("point", ""),
                    "quote": cp.get("quote", ""),
                    "page": cp.get("page"),
                    "ward_tags": classify(text, WARD_AXIS),
                    "disease_tags": classify(text, DISEASE_AXIS),
                    "theme_tags": classify(text, THEME_AXIS),
                    "deadline": extract_deadline(text) if cp.get("type") == "経過措置" else None,
                }
            )
    return results


def render_item(m: dict) -> list[str]:
    lines = []
    cat_label = CATEGORY_LABELS.get(m["category"], m["category"])
    page_label = f"（page {m['page']}）" if m.get("page") else ""
    sub_tags = m["disease_tags"] + m["theme_tags"]
    tag_label = f" `{' '.join(sub_tags)}`" if sub_tags else ""
    deadline_label = f" ⏰期限:{m['deadline']}" if m.get("deadline") else ""
    lines.append(f"- [{cat_label}][{m['type']}]{deadline_label} **{m['point']}**{tag_label} {page_label}")
    lines.append(f"  > {m['quote']}")
    lines.append(f"  - {m['title']}")
    lines.append(f"  - {m['url']}")
    lines.append("")
    return lines


def render_section(section_title: str, items: list[dict]) -> list[str]:
    """
    セクション内をテーマ軸（軸③）ごとの小見出しに分割して表示する。
    「病院PT管理職プロファイル」向け：現場運用に直結するテーマを優先表示する。
    どのテーマにも一致しない項目は最後に「その他」として出す。

    表示順は「見せ方の優先度」であって、DBの並びやFactの重要度そのものではない。
    優先順位を変えたければ THEME_DISPLAY_ORDER を並び替えるだけでよい。
    """
    lines = [f"## ① {section_title}", ""]

    shown_ids = set()
    for theme_label in THEME_DISPLAY_ORDER:
        theme_items = [m for m in items if theme_label in m["theme_tags"] and id(m) not in shown_ids]
        if not theme_items:
            continue
        lines.append(f"#### {theme_label}")
        lines.append("")
        for m in theme_items:
            lines.extend(render_item(m))
            shown_ids.add(id(m))

    other_items = [m for m in items if id(m) not in shown_ids]
    if other_items:
        lines.append("#### その他")
        lines.append("")
        for m in other_items:
            lines.extend(render_item(m))

    return lines


# 病院PT管理職プロファイル：現場運用に直結する順にテーマを並べる。
# 「点数・算定要件」は事務長プロファイルでも上位に来る想定だが、
# ここでは管理職の日常業務（研修計画・計画書運用・離床可否判断）を優先する。
THEME_DISPLAY_ORDER = ["離床・ベッド上", "計画書・記録", "多職種・研修", "点数・算定要件", "経過措置"]


def render_markdown(mentions: list[dict], audience: str) -> str:
    if audience == "admin":
        mentions = [m for m in mentions if is_admin_relevant(m)]

    title_suffix = "事務長向け報告" if audience == "admin" else "リハ職員向け運用連絡"
    lines = []
    lines.append(f"# {KEYWORD} 関連レポート（{title_suffix}）")
    lines.append("")
    lines.append(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    if audience == "admin":
        lines.append(
            "収益構造・届出に関わる変更点（新設・廃止・要件変更・経過措置）のみを対象にしています。"
            "運用解釈の確認（明確化）はリハ職員向けレポートを参照してください。"
        )
    else:
        lines.append(
            "「共通」（全病棟に関わる可能性がある変更点）を先頭に、"
            "そのあとに病棟・算定区分（軸①）別のセクションを続けています。"
            "自施設の病棟種別に該当するセクションと「共通」だけを読めば、"
            "関係の薄い区分の変更点を読み飛ばせます。"
        )
    lines.append("")
    lines.append(
        "各セクション内はさらにテーマ（軸③）ごとに小見出し分割しています"
        "（離床・ベッド上 → 計画書・記録 → 多職種・研修 → 点数・算定要件 → 経過措置 → その他 の順）。"
        "この並び順は「見せ方」であり、元データ（change_points）や重要度そのものを表すものではありません。"
    )
    lines.append("")
    lines.append(
        "各項目には疾患別（軸②）・テーマ（軸③）のタグを "
        "`回復期` のように併記しています。キーワード一致による機械分類のため、"
        "分類ミスや複数区分にまたがる項目がある点はご留意ください。"
    )
    lines.append("")

    ward_assigned = set()
    for ward_label, _ in WARD_AXIS:
        for m in mentions:
            if ward_label in m["ward_tags"]:
                ward_assigned.add(id(m))

    # 「共通」を先頭に表示する。
    # 離床規定・早期リハ加算の見直しのような、病棟を問わず影響が大きい変更点が
    # ここに集まりやすいため、病棟別セクションより先に読めるようにする。
    common_items = [m for m in mentions if id(m) not in ward_assigned]
    if common_items:
        lines.extend(
            render_section("共通（特定の病棟区分に限定されない、または病棟を特定できない変更点）", common_items)
        )

    for ward_label, _ in WARD_AXIS:
        items = [m for m in mentions if ward_label in m["ward_tags"]]
        if not items:
            continue
        lines.extend(render_section(ward_label, items))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audience", choices=["staff", "admin"], default="staff")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    mentions = fetch_mentions(conn, KEYWORD)
    markdown = render_markdown(mentions, args.audience)

    output = f"reports/rehabili_hierarchy_{args.audience}_report.md"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(markdown)

    if args.audience == "admin":
        mentions = [m for m in mentions if is_admin_relevant(m)]

    print(f"レポート生成完了: {output}")
    print(f"  対象件数: {len(mentions)}件")
    for ward_label, _ in WARD_AXIS:
        count = sum(1 for m in mentions if ward_label in m["ward_tags"])
        print(f"    {ward_label}: {count}件")
    common_count = sum(
        1 for m in mentions if not any(ward_label in m["ward_tags"] for ward_label, _ in WARD_AXIS)
    )
    print(f"    共通: {common_count}件")

    conn.close()


if __name__ == "__main__":
    main()
