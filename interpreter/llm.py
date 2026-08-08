"""
LLMバックエンドの共通インターフェース。

設計方針：
    PDF → 抽出 → [LLM] → DB
                   ↑
            ここだけ差し替え可能にする

  - summarize.py は llm.interpret(title, prompt_text, backend=...) だけを呼ぶ。
    Claude / Ollama / LM Studio のどれを使うかを意識しない。
  - プロンプト内容（SYSTEM_PROMPT）とJSON整形ロジックはモデルに依存しないため、
    ここに集約する。各backendモジュール（claude.py / local.py）は
    「テキストを投げて生テキストを受け取る」薄い層に徹する。
  - PROMPT_VERSION はプロンプトの版。内容を変えたら上げる。
    model_used と組み合わせて「どのモデル×どのプロンプト版で生成したか」を
    document_topic 側で追跡できるようにする。
"""

import json

PROMPT_VERSION = "interpret-v0.1"

VALID_TYPES = {"新設", "要件変更", "明確化", "経過措置", "廃止", "その他"}

TOOL_NAME = "record_interpretation"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "診療報酬改定資料の本文から、変更点と訪問看護への言及を構造化して記録する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "change_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": sorted(VALID_TYPES),
                            "description": "分類。迷ったら『その他』を使うこと。無理に分類しない。",
                        },
                        "point": {
                            "type": "string",
                            "description": "何がどう変わった/明記されているかを本文の記述に基づき1文で",
                        },
                        "quote": {
                            "type": "string",
                            "description": (
                                "根拠となる本文中の該当箇所。本文の文字列をそのまま抜粋すること。"
                                "要約・言い換え・改変は禁止。必ず本文中の1箇所の連続した文章のみを抜粋し、"
                                "離れた場所にある複数の文をつなぎ合わせて1つの抜粋のように示すことは禁止。"
                            ),
                        },
                        "page": {"type": "integer", "description": "抜粋元のページ番号"},
                    },
                    "required": ["type", "point", "quote", "page"],
                },
            },
            "houmon_kango_related": {
                "type": "boolean",
                "description": (
                    "本文中に訪問看護・訪問看護ステーションに関する記述が存在するかどうかの機械的判定。"
                    "関係しそうだと『思う』かではなく、実際にその語句・話題への言及が本文にあるかどうかで判定する。"
                ),
            },
            "houmon_kango_mentions": {
                "type": "array",
                "description": "houmon_kango_relatedがfalseの場合は空配列",
                "items": {
                    "type": "object",
                    "properties": {
                        "excerpt": {
                            "type": "string",
                            "description": (
                                "訪問看護に関する記述の該当箇所を本文からそのまま抜粋。要約禁止。"
                                "必ず1箇所の連続した文章のみとし、複数の離れた箇所をつなぎ合わせないこと。"
                                "訪問看護への言及が複数箇所にある場合は、この配列に複数要素として分けて入れること。"
                            ),
                        },
                        "page": {"type": "integer"},
                    },
                    "required": ["excerpt", "page"],
                },
            },
        },
        "required": ["change_points", "houmon_kango_related", "houmon_kango_mentions"],
    },
}

SYSTEM_PROMPT = """あなたは診療報酬改定資料から、記載されている事実を構造化して抽出するアシスタントです。
資料に書かれていない推測・一般的な医学知識・制度への評価は一切加えないでください。
本文に明記されていることだけを抽出対象とします。
quoteやexcerptは本文からの逐語抜粋のみとし、要約・言い換え・複数箇所の結合は禁止です。
"""

# Ollama等、tool useに対応していないバックエンド向けの自由記述JSON形式プロンプト。
# Claudeバックエンドはtool use（TOOL_SCHEMA）を使うため、こちらのJSON整形指示は使わない。
FREEFORM_JSON_INSTRUCTIONS = """
以下のJSON形式のみで出力してください。前置き・Markdown記法・説明文は一切不要です。

{
  "change_points": [
    {
      "type": "新設 | 要件変更 | 明確化 | 経過措置 | 廃止 | その他 のいずれか",
      "point": "何がどう変わった/明記されているかを本文の記述に基づき1文で",
      "quote": "根拠となる本文中の該当箇所。本文の文字列をそのまま抜粋すること。",
      "page": 抜粋元のページ番号（整数）
    }
  ],
  "houmon_kango_related": true または false,
  "houmon_kango_mentions": [
    {"excerpt": "訪問看護に関する記述の該当箇所をそのまま抜粋", "page": 抜粋元のページ番号（整数）}
  ]
}
"""


def build_user_message(title: str, prompt_text: str) -> str:
    return f"資料タイトル: {title}\n\n本文（ページ番号付き）:\n{prompt_text}"


def parse_json_response(raw_text: str) -> dict:
    """
    モデルの生出力からJSON部分を取り出す共通ロジック。
    コードフェンス（```json ... ```）が付いていても剥がして解釈する。
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    return json.loads(cleaned)


def get_backend(name: str):
    """
    backend名から interpret(title, prompt_text, **kwargs) -> (result: dict, model_used: str)
    を返す。呼び出し側（summarize.py）はこれ以上バックエンドの詳細を知らなくてよい。
    """
    if name == "claude":
        from interpreter.claude import interpret

        return interpret
    if name in ("ollama", "local"):
        from interpreter.local import interpret

        return interpret
    raise ValueError(f"未対応のbackend: {name}（'claude' か 'ollama' を指定）")
