# kaitei-tracker

令和８年度診療報酬改定に関する各種資料（説明資料・疑義解釈・今後は通知等も）を
自動収集し、`revision_document` という単一のFactテーブルに蓄積するツール。

## アーキテクチャ

```
kaitei-tracker/
├── common/
│   ├── db.py       ← revision_documentへの共通アクセス層（upsert・非アクティブ化）
│   └── wareki.py   ← 令和→西暦の日付変換ユーティリティ
├── scraper/
│   ├── scrape_summary.py  ← 説明資料一覧ページ用
│   └── scrape_gigi.py     ← 改定ハブページの疑義解釈セクション用
├── db/
│   └── kaitei.db   ← 統合SQLite（categoryで種別を分ける）
├── tests/
│   ├── fixture_summary.html
│   └── fixture_hub.html
└── .github/workflows/scrape.yml
```

**設計方針**：スクレイパ対象を増やす時は `scraper/` にファイルを追加するだけ。
DBスキーマは触らない。`category`列で種別（'summary' / 'gigi' / 将来の 'notification' 等）を分ける。

## revision_document テーブル

| カラム | 内容 |
|---|---|
| category | 'summary'（説明資料）/ 'gigi'（疑義解釈）等 |
| title | 資料タイトル |
| published_at | 資料に記載の日付（ISO形式、分からない場合はNULL） |
| url | PDF等へのリンク（UNIQUE） |
| source_page | どのハブページから拾ったか |
| size | ファイルサイズ表記 |
| content_hash | 将来の差分検知用に予約 |
| is_priority | 訪問看護・在宅医療関連なら1 |
| fetched_at | このツールが検知した日時 |
| is_active | 元ページから消えたら0（削除はしない＝Factは永続化） |

ここに保存するのはFactのみ。「重要かどうか」「何が変わったか」といった
Interpretationは今回のスコープ外（将来 `document_topic` 等を別テーブルで追加する想定）。

## セットアップ

```bash
pip install -r requirements.txt

# ローカルテスト（ネットワーク不要）
python scraper/scrape_summary.py --test-file tests/fixture_summary.html
python scraper/scrape_gigi.py --test-file tests/fixture_hub.html

# 本番実行
python scraper/scrape_summary.py
python scraper/scrape_gigi.py
```

## 既存リポジトリ（v1）からの移行手順

旧構成（`scraper.py`が直下、`db/kaitei_fact.db`）から今回の構成に切り替える場合：

```bash
# 1. 旧ファイルを削除
git rm scraper.py
git rm -r db/kaitei_fact.db   # 旧DBは役目を終えたので削除してOK
                                 # （Factは新しいDBに載せ替えることになるが、
                                 #   ページ自体は毎回全件取得し直すので実害なし）

# 2. 新しいファイル一式をコピー
#    (common/, scraper/, tests/, requirements.txt, .github/workflows/scrape.yml, README.md)

# 3. コミット
git add .
git commit -m "refactor: revision_document テーブルに統合、疑義解釈スクレイパを追加"
git push
```

Actionsの手動実行（Run workflow）で、`db/kaitei.db` が新規作成され、
説明資料24件・疑義解釈13件（本記事執筆時点）が入るはず。

## クエリ例

```sql
-- 疑義解釈だけを新しい順に
SELECT published_at, title, url FROM revision_document
WHERE category = 'gigi' AND is_active = 1
ORDER BY published_at DESC;

-- 訪問看護・在宅医療関連のみ（カテゴリ横断）
SELECT category, title, url FROM revision_document
WHERE is_priority = 1 AND is_active = 1;
```

## Interpretation層（document_topic）

`revision_document`（Fact）の中身をLLMで読ませて構造化抽出する仕組み。
**LLMバックエンドを差し替え可能な設計**にしてある：

```
PDF → 抽出 → [LLM: --backend で切替] → DB
                ↑
       ┌────────┼────────┐
       │                 │
    claude.py        local.py (Ollama)
```

```
interpreter/
├── summarize.py   ← PDF取得・抽出・quote検証・DB保存（バックエンド非依存）
├── llm.py          ← 共通インターフェース（プロンプト定義・JSON整形・backend選択）
├── claude.py       ← Claude APIバックエンド
└── local.py        ← Ollamaバックエンド（RTX4070 Super等のローカルGPU運用を想定）
```

`summarize.py`はモデルの詳細を一切知らず、`llm.get_backend(name)`が返す
`interpret(title, prompt_text) -> (result, model_used)`だけを呼ぶ。
モデルを変える時は`--backend`と`--model`を変えるだけで、PDF処理・DB保存のコードは触らない。

`model_used`と`prompt_version`を必ず記録するため、後から
「同じPDFをClaudeとQwenで処理した場合の解釈の違い」のような比較ができる。

### 使い方

```bash
# ローカルでパイプラインだけ確認（LLM呼び出しなし）
python interpreter/summarize.py --category gigi --limit 1 --dry-run

# 単発のPDFファイルでテスト
python interpreter/summarize.py --test-pdf tests/sample_gigi.pdf --test-title "テスト" --dry-run

# 本番実行：Claude（既定、要 ANTHROPIC_API_KEY 環境変数）
python interpreter/summarize.py --category gigi --limit 1

# 本番実行：ローカルLLM（Ollama、事前に `ollama serve` と `ollama pull qwen2.5:14b-instruct` が必要）
python interpreter/summarize.py --category gigi --limit 1 --backend ollama
python interpreter/summarize.py --category gigi --limit 1 --backend ollama --model gemma2:9b
```

GitHub Actions上（Claude利用時）は、リポジトリの Settings → Secrets and variables → Actions で
`ANTHROPIC_API_KEY` を登録した上で、Actionsタブの「資料の解釈生成（Claude API）」を手動実行する。
category・limitは実行時に入力できる。
（OllamaバックエンドはローカルGPUが必要なため、GitHub Actions上では現状想定していない）

### document_topic テーブル（2026-08-08 設計レビュー反映）

Claudeの役割を「評価」ではなく「本文に書かれている変更点の構造化抽出」に限定している。

| カラム | 内容 |
|---|---|
| document_id | revision_document.id への参照 |
| change_points | JSON配列。各要素は `{type, point, quote, page}` |
| houmon_kango_related | 本文に訪問看護への言及が**存在したか**という機械的事実（「影響するか」の評価ではない） |
| houmon_kango_excerpt | 言及があれば原文をそのまま抜粋 |
| source_content_hash | 生成時点のrevision_document.content_hash |
| model_used | 使用したモデル名 |
| prompt_version | 例: 'interpret-v0.1'。プロンプト改訂時に版を上げることで、同じ資料に対する複数バージョンの解釈を区別できる |
| generated_at | 生成日時 |

**change_pointsの各要素**：
- `type`：新設/要件変更/明確化/経過措置/廃止/その他。これは分類判断＝Interpretationであり、Factとしては扱わない。無理に5分類へ押し込ませず「その他」を許容している。
- `point`：本文の記述に基づく1文要約
- `quote`：根拠となる本文中の該当箇所。**要約・言い換えは禁止**、逐語抜粋のみ。
- `page`：抜粋元のページ番号

**quoteの自動検証**：生成後、`quote`と`houmon_kango_excerpt`が実際にPDF本文に存在するかを
文字列一致で機械的に検証し、結果をコンソールに出力する（`✓`/`✗`表示）。本文に無い文言が
混入していないかを人間が確認する前の一次スクリーニングとして機能する。

ただし以下は自動検証できないため、**必ず人間の目で確認すること**：
- `point`が`quote`から逸脱していないか（過度な一般化・拡大解釈をしていないか）
- 本文に無い一般知識・医学的判断が混ざっていないか

**revision_documentの不変性チェック**：実行前後で`revision_document`の件数・内容を
比較し、Fact層が一切変更されていないことをコンソールに出力して確認する。

`get_pending_documents()`は「document_topicが無い」または「元資料のcontent_hashが変わった」
ものだけを対象にするため、同じ条件で繰り返し実行しても重複生成しない。

### 初回導入時の受入テスト手順

```bash
python interpreter/summarize.py --category gigi --limit 1
```

実行後、コンソール出力と`document_topic`の中身を見て、以下を確認する：

1. `quote`は実際にPDF本文に存在するか（✓表示になっているか）
2. `point`は`quote`の内容から逸脱していないか
3. `page`は正しいか
4. `houmon_kango_excerpt`は原文そのままか
5. Claudeが本文にない一般知識を混ぜていないか
6. `revision_document`は一切変更されていないか（「revision_documentは不変であることを確認」と出ているか）

①〜⑤が問題なければ`--limit 3`など件数を増やしていく。

**現状の制約**：`content_hash`は現状 URL とタイトルから算出しており、PDF本文そのものの
ハッシュではない。そのため、厚労省がURLを変えずにPDFの中身だけ差し替えた場合は検知できない。
（今回観測した範囲では、資料差し替え時はURL自体も変わっていたため実用上の影響は小さいと想定）

## 今後の拡張候補

- `scraper/scrape_notification.py`：告示・通知（第３〜５章）
- `scraper/scrape_yakka.py`：薬価改定関連
- 差分検知時のGitHub Issue自動発行
- スキャンPDF（画像のみ）対応：OCR処理の追加
