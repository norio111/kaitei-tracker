# kaitei-tracker

令和８年度診療報酬改定説明資料ページ（厚労省）を毎日自動チェックし、
新規・差し替え資料をSQLiteに記録するツール。

## 設計方針

- **Fact層のみを永続化**：資料の出現日時・URL・サイズを記録。中身の解釈（訪問看護への影響など）はここでは行わない
- **差し替え検知**：厚労省がPDFを差し替えるとURLが変わるため、旧URLは`is_active=0`にして残す（削除しない）
- **優先タグ**：資料名に「訪問看護」「在宅医療」を含むものは `is_priority=1` を付与

## セットアップ手順

1. このディレクトリの中身をGitHubリポジトリにpush
   ```bash
   git init
   git add .
   git commit -m "init"
   git remote add origin <あなたのリポジトリURL>
   git branch -M main
   git push -u origin main
   ```

2. リポジトリの Settings → Actions → General →
   "Workflow permissions" を **Read and write permissions** に変更
   （scraper.pyがdb/を自動コミットするため）

3. 初回は手動実行して動作確認
   - GitHubリポジトリの Actions タブ → 「診療報酬改定チェック」→ Run workflow

4. 以降は毎日 JST 9:00 に自動実行される（cron: `0 0 * * *`）

## ローカルでの動作確認

```bash
pip install -r requirements.txt

# 本番URLに接続してテスト
python scraper.py

# ローカルのテストHTMLで動作確認（ネットワーク不要）
python scraper.py --test-file tests/fixture_page.html
```

## DBの中身を見る

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('db/kaitei_fact.db')
for row in conn.execute('SELECT * FROM kaitei_fact WHERE is_active=1'):
    print(row)
"
```

## 次のステップ（Interpretation層）

このスクリプトはFactの検知のみ。中身の解釈（訪問看護療養費への影響評価など）は
別スクリプトで `kaitei_interpretation` テーブルに書き込む想定：

```sql
CREATE TABLE kaitei_interpretation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER REFERENCES kaitei_fact(id),
    summary TEXT,
    impact_on_houmon_kango TEXT,  -- 訪問看護への影響
    generated_at TEXT,
    model_used TEXT
);
```

PDFの中身をClaude APIに読ませて自動要約する処理は、このFact検知の後段に
別ジョブとして追加できる。
