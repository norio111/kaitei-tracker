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

## 今後の拡張候補

- `scraper/scrape_notification.py`：告示・通知（第３〜５章）
- `scraper/scrape_yakka.py`：薬価改定関連
- `document_topic` テーブル：LLMによる内容要約・影響評価（Interpretation層）
- 差分検知時のGitHub Issue自動発行
