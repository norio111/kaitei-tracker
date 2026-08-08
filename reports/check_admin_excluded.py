"""
generate_rehabili_hierarchy.py --audience admin で除外された項目
（type=明確化 が中心）を一覧表示し、除外が妥当か目視確認するためのスクリプト。

使い方：
    python reports/check_admin_excluded.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3

import reports.generate_rehabili_hierarchy as gr
from common.db import DB_PATH


def main():
    conn = sqlite3.connect(DB_PATH)
    mentions = gr.fetch_mentions(conn, gr.KEYWORD)

    excluded = [m for m in mentions if not gr.is_admin_relevant(m)]
    print(f"admin版から除外された項目: {len(excluded)}件\n")

    for i, m in enumerate(excluded, 1):
        print(f"[{i}] type={m['type']}")
        print(f"    point: {m['point']}")
        print(f"    quote: {m['quote'][:120]}")
        print(f"    出典: {m['title']}")
        print()

    conn.close()


if __name__ == "__main__":
    main()
