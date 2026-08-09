"""
generate_rehabili_hierarchy.py --audience admin の is_admin_priority() が
何を根拠に⭐を付けているかを、条件別（type / calculation_decision / revenue_signal）
に分解して表示する診断スクリプト。

目的：
    2026-08-08のrun（26件中23件が⭐）で識別力が落ちていることが判明。
    どの条件が支配的になっているか（＝revenue_signalがリハビリ領域で
    ほぼ全件に光ってしまっているという仮説）を実データで確認する。

使い方：
    python reports/check_admin_priority_breakdown.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3

import reports.generate_rehabili_hierarchy as gr
from common.db import DB_PATH
from reports.signals import has_revenue_signal, is_calculation_decision


def classify_trigger(m: dict) -> list[str]:
    """admin_priority=Trueの根拠となった条件をすべて返す（複数該当もあり得る）。"""
    triggers = []
    if m["type"] in gr.ADMIN_RELEVANT_TYPES:
        triggers.append("type")
    text = f"{m['point']} {m['quote']}"
    if is_calculation_decision(text):
        triggers.append("calc")
    if has_revenue_signal(text):
        triggers.append("revenue")
    return triggers


def main():
    conn = sqlite3.connect(DB_PATH)
    mentions = gr.fetch_mentions(conn, gr.KEYWORD)
    conn.close()

    total = len(mentions)
    starred = [m for m in mentions if m["admin_priority"]]
    unstarred = [m for m in mentions if not m["admin_priority"]]

    # --- 条件別の内訳（starredの中で、どの条件がヒットしたか） ---
    trigger_counts = {"type": 0, "calc": 0, "revenue": 0}
    revenue_only_count = 0
    for m in starred:
        triggers = classify_trigger(m)
        for t in triggers:
            trigger_counts[t] += 1
        if triggers == ["revenue"]:
            revenue_only_count += 1

    print(f"総件数: {total}件")
    print(f"⭐あり: {len(starred)}件 / ⭐なし: {len(unstarred)}件\n")
    print("⭐該当理由の内訳（重複あり。1件が複数条件に該当することもある）:")
    print(f"  type一致        : {trigger_counts['type']}件")
    print(f"  calculation一致  : {trigger_counts['calc']}件")
    print(f"  revenue_signal一致: {trigger_counts['revenue']}件")
    print(f"  → revenue_signalのみで⭐が付いた件数: {revenue_only_count}件\n")

    # --- 「明確化」type限定で、⭐あり/なしそれぞれの中身を見せる ---
    meikakuka = [m for m in mentions if m["type"] == "明確化"]
    meikakuka_starred = [m for m in meikakuka if m["admin_priority"]]
    meikakuka_unstarred = [m for m in meikakuka if not m["admin_priority"]]

    print(f"--- type=明確化（{len(meikakuka)}件中、⭐あり{len(meikakuka_starred)}件 / ⭐なし{len(meikakuka_unstarred)}件） ---\n")

    print("[⭐あり・明確化]")
    for i, m in enumerate(meikakuka_starred, 1):
        triggers = classify_trigger(m)
        print(f"  [{i}] 根拠={triggers}")
        print(f"      point: {m['point']}")
        print()

    print("[⭐なし・明確化]")
    for i, m in enumerate(meikakuka_unstarred, 1):
        print(f"  [{i}] point: {m['point']}")
        print()


if __name__ == "__main__":
    main()
