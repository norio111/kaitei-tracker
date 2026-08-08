"""
revision_document のうち、まだ解釈（document_topic）が無いものを対象に、
PDF本文をLLMで「構造化抽出」し、document_topicに保存する。

このファイルはPDF取得・抽出・quote検証・DB保存にのみ責務を持つ。
LLM呼び出し自体は interpreter/llm.py 経由でバックエンド（claude.py / local.py）に委譲する。
    PDF → 抽出 → [LLM: --backend で切替] → DB
モデルを変えても、このファイルは変更不要（--backend / --model を変えるだけ）。

設計方針（2026-08-08 設計レビュー反映）：
  - revision_document（Fact）は一切書き換えない。実行前後で件数・内容を比較し確認する。
  - LLMの役割は「評価」ではなく「本文に書かれている変更点の構造化抽出」に限定する
    （quoteは逐語抜粋のみ、typeは無理に分類させず「その他」を許容、
      houmon_kango_relatedは「言及の有無」という機械的事実であって「影響評価」ではない）。
  - quote / houmon_kango_excerpt は生成後にPDF本文と突き合わせて自動検証する。
  - model_used と prompt_version を必ず記録し、モデルを変えた場合の比較を可能にする。
  - API費用が発生し得るため、cronでの自動実行はせず手動トリガーのみとする。

使い方：
    python interpreter/summarize.py --category gigi --limit 1                     # Claude（既定）
    python interpreter/summarize.py --category gigi --limit 1 --backend ollama    # ローカルLLM
    python interpreter/summarize.py --dry-run --test-pdf tests/sample_gigi.pdf --test-title "テスト"
"""

import argparse
import io
import json
import os
import re
import sys

import pdfplumber
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.db import (  # noqa: E402
    get_connection,
    get_pending_documents,
    insert_interpretation,
    snapshot_revision_document,
)
from interpreter.llm import PROMPT_VERSION, VALID_TYPES, get_backend  # noqa: E402

MAX_PAGES = 8
MAX_CHARS = 12000


def download_pdf_bytes(url: str) -> bytes:
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    res.raise_for_status()
    return res.content


def extract_pages(pdf_bytes: bytes, max_pages: int = MAX_PAGES) -> list[tuple[int, str]]:
    """[(page_number(1始まり), page_text), ...] を返す"""
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages], start=1):
            text = page.extract_text() or ""
            pages.append((i, text))
    return pages


def build_prompt_text(pages: list[tuple[int, str]], max_chars: int = MAX_CHARS) -> str:
    blocks = []
    total = 0
    for page_no, text in pages:
        block = f"[page {page_no}]\n{text}\n"
        if total + len(block) > max_chars:
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def _normalize(s: str) -> str:
    """PDF抽出特有の余分な空白差異を吸収して比較するための正規化"""
    return re.sub(r"\s+", "", s or "")


def verify_quote(quote: str, pages: list[tuple[int, str]], page_no: int | None) -> tuple[bool, str]:
    if not quote:
        return False, "quoteが空"

    norm_quote = _normalize(quote)

    if page_no is not None:
        page_text = next((t for n, t in pages if n == page_no), None)
        if page_text is not None and norm_quote in _normalize(page_text):
            return True, f"page {page_no} 内で一致"

    for n, t in pages:
        if norm_quote in _normalize(t):
            return True, f"page {n} で一致（指定page={page_no}とズレあり）"

    return False, "全ページ中に該当文字列が見つからない"


def print_verification_report(result: dict, pages: list[tuple[int, str]]) -> None:
    print("\n  --- 受入テスト自動チェック ---")
    change_points = result.get("change_points", [])
    all_ok = True

    for i, cp in enumerate(change_points, start=1):
        t = cp.get("type", "")
        type_ok = t in VALID_TYPES
        verified, detail = verify_quote(cp.get("quote", ""), pages, cp.get("page"))
        all_ok = all_ok and verified
        mark = "✓" if verified else "✗"
        print(f"  [{i}] type={t}{'' if type_ok else '（想定外の値！要確認）'}")
        print(f"      point: {cp.get('point', '')}")
        print(f"      quote: {cp.get('quote', '')}")
        print(f"      {mark} 逐語検証: {detail}")

    if result.get("houmon_kango_related"):
        excerpt = result.get("houmon_kango_excerpt", "")
        verified, detail = verify_quote(excerpt, pages, None)
        all_ok = all_ok and verified
        mark = "✓" if verified else "✗"
        print(f"  houmon_kango_excerpt: {excerpt}")
        print(f"  {mark} 逐語検証: {detail}")
    else:
        print("  houmon_kango_related: false（訪問看護への言及なしと判定）")

    print(f"\n  総合: {'✓ 全quote検証OK' if all_ok else '✗ 検証NGのquoteあり。人間による確認が必要'}")
    print("  ※ pointがquoteから逸脱していないか、本文にない一般論が混ざっていないかは")
    print("    自動検証できないため、必ず人間の目で確認してください。")


def process_one(conn, doc: dict, interpret_fn, model: str | None, dry_run: bool) -> None:
    print(f"  → {doc['title'][:60]}...")

    pdf_bytes = download_pdf_bytes(doc["url"])
    pages = extract_pages(pdf_bytes)
    if not any(t.strip() for _, t in pages):
        print("    ⚠ テキスト抽出できず（スキャンPDFの可能性）、スキップ")
        return

    prompt_text = build_prompt_text(pages)

    if dry_run:
        result = {
            "change_points": [{"type": "その他", "point": "[DRY RUN]", "quote": "[DRY RUN]", "page": 1}],
            "houmon_kango_related": False,
            "houmon_kango_excerpt": "",
        }
        model_used = "dry-run"
    else:
        kwargs = {"model": model} if model else {}
        result, model_used = interpret_fn(doc["title"], prompt_text, **kwargs)
        print_verification_report(result, pages)

    insert_interpretation(
        conn,
        document_id=doc["id"],
        change_points_json=json.dumps(result.get("change_points", []), ensure_ascii=False),
        houmon_kango_related=bool(result.get("houmon_kango_related")),
        houmon_kango_excerpt=result.get("houmon_kango_excerpt", ""),
        source_content_hash=doc["content_hash"],
        model_used=model_used,
        prompt_version=PROMPT_VERSION,
    )
    print(f"    → document_topic に保存しました（model_used={model_used}）")


def process_local_test(interpret_fn, model: str | None, dry_run: bool, test_pdf: str, test_title: str) -> None:
    with open(test_pdf, "rb") as f:
        pdf_bytes = f.read()
    pages = extract_pages(pdf_bytes)
    prompt_text = build_prompt_text(pages)
    print(f"抽出ページ数: {len(pages)} / 合計文字数: {sum(len(t) for _, t in pages)}")

    if dry_run:
        print("\n[DRY RUN] LLM呼び出しはスキップ")
        print(prompt_text[:300])
        return

    kwargs = {"model": model} if model else {}
    result, model_used = interpret_fn(test_title, prompt_text, **kwargs)
    print(f"\n=== 結果（model_used={model_used}） ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print_verification_report(result, pages)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", help="'gigi' や 'summary' 等。省略時は全カテゴリ対象")
    parser.add_argument("--limit", type=int, default=1, help="1回の実行で処理する最大件数（コスト管理）")
    parser.add_argument("--backend", default="claude", choices=["claude", "ollama"], help="使用するLLMバックエンド")
    parser.add_argument("--model", help="バックエンド内のモデル名を上書き（省略時は各backendの既定値）")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しをせずパイプラインだけ確認する")
    parser.add_argument("--test-pdf", help="DBを介さず、指定したローカルPDFファイル単体でテストする")
    parser.add_argument("--test-title", default="テスト資料")
    args = parser.parse_args()

    if not args.dry_run and args.backend == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY が設定されていません（--dry-run で動作確認のみ可能）", file=sys.stderr)
        sys.exit(1)

    interpret_fn = get_backend(args.backend)

    if args.test_pdf:
        process_local_test(interpret_fn, args.model, args.dry_run, args.test_pdf, args.test_title)
        return

    conn = get_connection()
    before_snapshot = snapshot_revision_document(conn)

    pending = get_pending_documents(conn, category=args.category, limit=args.limit)
    print(f"未解釈の資料: {len(pending)}件（category={args.category or '全て'}, limit={args.limit}, backend={args.backend}）")

    for doc in pending:
        try:
            process_one(conn, doc, interpret_fn, args.model, args.dry_run)
        except Exception as e:  # noqa: BLE001
            print(f"    ✗ 失敗: {e}", file=sys.stderr)

    after_snapshot = snapshot_revision_document(conn)
    if before_snapshot != after_snapshot:
        print(f"\n⚠⚠⚠ revision_document が変化しています！ before={before_snapshot} after={after_snapshot}", file=sys.stderr)
    else:
        print(f"\n✓ revision_document は不変であることを確認（{before_snapshot[0]}件のまま）")

    conn.close()


if __name__ == "__main__":
    main()
