"""
change_point の point/quote から、以下2つの「見せ方シグナル」を検出する共通関数。
特定のペルソナ（事務長/リハ管理職等）に固有の機能ではなく、
どのレポートでも「収益に関わるか」「期限があるか」は判断材料になるため、
ここに集約して全レポートスクリプトで共有する。

  - has_revenue_signal(): 点数・金額・加算/減算等の語を含むか（💰の判定材料）
  - extract_deadline(): 経過措置等の期限日を本文から抽出する（⏰の判定材料）

document_topic 側には一切保存しない。あくまで表示時に都度計算する
「Persona View層」の一部（Factの再解釈ではなく見せ方）という位置づけ。
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.wareki import extract_date  # noqa: E402

REVENUE_SIGNAL_PATTERN = re.compile(r"\d+\s*点|\d+\s*円|\d+\s*[%％]|加算|減算|引き上げ|引下げ|引き下げ")

# 「明確化」type であっても、算定可否そのものへの言及がある場合は
# 収益・事務判断に直結するため、事務長向けレポートで拾いたい項目。
# 例：「算定できる」「算定することができる」「届出を認める」など、
# 疑義解釈のQ&Aに頻出する言い回し。日本語は「算定」と可否語の間に
# 「することが」等が挟まる場合が多いため、間に短い語句が入っても
# 一致するよう .{0,8} で許容する。
CALCULATION_DECISION_PATTERN = re.compile(
    r"算定.{0,8}(できる|できない|可能|不可)|届出を認め(る|ない)|併算定.{0,8}(できる|できない|可能|不可)"
)


def is_calculation_decision(text: str) -> bool:
    return bool(CALCULATION_DECISION_PATTERN.search(text))


def has_revenue_signal(text: str) -> bool:
    return bool(REVENUE_SIGNAL_PATTERN.search(text))


def extract_deadline(text: str) -> str | None:
    """経過措置等、期限が本文にあれば ISO日付 で返す。無ければ None。"""
    return extract_date(text)


def signal_labels(point: str, quote: str, is_keigen_sochi: bool) -> str:
    """
    レポート表示用の接頭ラベルを組み立てる。
    is_keigen_sochi: type=='経過措置' かどうか（期限抽出を試みるかの判定に使う）
    """
    text = f"{point} {quote}"
    labels = []
    if has_revenue_signal(text):
        labels.append("💰")
    if is_keigen_sochi:
        deadline = extract_deadline(text)
        if deadline:
            labels.append(f"⏰期限:{deadline}")
    return " ".join(labels)
