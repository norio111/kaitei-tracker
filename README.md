# kaitei-tracker

令和8年度診療報酬改定の説明資料と疑義解釈を厚生労働省のページから集めてSQLiteに蓄積し、LLMで本文から変更点を抜き出す試作ツールです。訪問看護・在宅医療に関係する資料には印を付けます。

## しくみ

```
厚労省の公開ページ
   ↓ scraper/       資料のタイトル・日付・URLを集める（Fact）
revision_document
   ↓ interpreter/   PDFを読み、LLMで変更点を本文から抜き出す（Interpretation）
document_topic
   ↓ reports/       事務長向け・リハビリ領域向けに並べ替えて出力する
```

集めた事実（Fact）と、LLMによる解釈（Interpretation）は別のテーブルに分けています。解釈を作り直しても、元の事実は変わりません。

## 構成

```
kaitei-tracker/
├─ common/        DBアクセス、和暦→西暦の変換
├─ scraper/       説明資料・疑義解釈の収集
├─ interpreter/   変更点の抽出（LLMの切り替え部分を含む）
├─ reports/       レポート出力と、判定条件を検証したスクリプト
├─ queries/       確認用SQL
├─ db/kaitei.db   収集結果と抽出結果
└─ tests/         ネットワークなしで試すための見本ファイル
```

## LLMの扱い

- LLMの役割は、重要度の「評価」ではなく、本文に書かれている変更点の「抜き出し」に限っています。
- 各変更点には、根拠となる本文の逐語の抜粋（quote）とページ番号を付けます。
- 生成後、quote が実際にPDF本文にあるかを文字列一致で自動確認します。
- 次の2点は自動では確認できないため、人が目で確認する前提です。
  - 要約が quote の内容から外れていないか
  - 本文にない一般知識が混ざっていないか
- 使ったモデル名とプロンプトの版を記録するため、同じ資料をモデル間で比べられます。
- LLMは Claude API とローカルの Ollama を `--backend` で切り替えられます。

## レポートと判定条件の検証

reports/ では、抜き出した変更点を事務長向けやリハビリ領域向けに並べて出力します。どの項目を優先表示するかの条件は、実データで確かめながら決めました。その経緯を [`DECISIONS.md`](DECISIONS.md) に記録しています。

- **K-001**：「明確化」の項目は重要度が低いという仮説を、実データで棄却
- **K-002**：優先表示の条件が識別力を失っていないかを確認
- **K-003**：否定表現（「算定できない」など）だけでは、制限の種類を分けられないことを確認
- **K-004**：1つの抜粋に複数の主張が含まれることがあり、さらに細かく分ける層が必要と判断

## 使い方

```bash
pip install -r requirements.txt

# ネットワークなしで収集処理を試す
python scraper/scrape_summary.py --test-file tests/fixture_summary.html
python scraper/scrape_gigi.py --test-file tests/fixture_hub.html

# 収集
python scraper/scrape_summary.py
python scraper/scrape_gigi.py

# 抽出の流れだけ確認する（LLMは呼ばない）
python interpreter/summarize.py --category gigi --limit 1 --dry-run

# 抽出（Claude。環境変数 ANTHROPIC_API_KEY が必要）
python interpreter/summarize.py --category gigi --limit 1

# 抽出（ローカルLLM。Ollama の起動とモデルの取得が必要）
python interpreter/summarize.py --category gigi --limit 1 --backend ollama
```

`.github/workflows/` に GitHub Actions 用の設定を置いていますが、現在は定期実行していません。

## 制約

- 資料の変化は URL とタイトルから判定しています。URLを変えずにPDFの中身だけ差し替えられた場合は検知できません。
- 画像だけのPDF（スキャン資料）には対応していません。
- 告示・通知は、まだ収集対象に入っていません。

## 出典と注意

- 資料は厚生労働省ウェブサイトで公開されているものを使っています。
- `db/kaitei.db` には、LLMが作った抽出結果も含まれます。誤りを含む可能性があり、算定の判断には使えません。必ず原本の資料を確認してください。
- 学習・検証用の試作です。

## 関連リポジトリ

診療報酬改定を、議論の段階からコードまで、段階ごとに分けて扱っています。

- [mhlw-update-pipeline](https://github.com/norio111/mhlw-update-pipeline)：中医協の議題から、訪問看護・在宅に関係するものを一次判定する
- **kaitei-tracker（このリポジトリ）**：改定後の説明資料・疑義解釈PDFから、変更点を抜き出す
- [med-code-map](https://github.com/norio111/med-code-map)：レセプト電算マスターを改定別に比べ、施設基準への影響を見る
- [gigi-ver-watch](https://github.com/norio111/gigi-ver-watch)：疑義解釈検索ツール（Excel）の更新を検知する