"""
Claude APIバックエンド。llm.get_backend('claude') 経由で使う。

設計変更（2026-08-08）：
    自由記述でJSONを書かせてから手動パースする方式は、長い日本語の抜粋を
    含む応答で「文字列が閉じられない」「エスケープが不正」といった解析エラーを
    繰り返し引き起こした（実運用で複数回確認）。
    Tool Use（構造化出力）に切り替えることで、モデルは決まったスキーマに
    沿ってデータを返すようになり、テキストとしてのJSON解析が原理的に不要になる。
"""

import os

from interpreter.llm import SYSTEM_PROMPT, TOOL_NAME, TOOL_SCHEMA, build_user_message

DEFAULT_MODEL = "claude-sonnet-4-6"


def interpret(title: str, prompt_text: str, model: str = DEFAULT_MODEL, api_key: str | None = None) -> tuple[dict, str]:
    import anthropic

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": build_user_message(title, prompt_text)}],
    )

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise RuntimeError(f"tool_useブロックが見つかりません。stop_reason={response.stop_reason}")

    # tool_use_block.input はAPI側で既にJSONとしてパース済みの辞書。
    # 手動でのJSON文字列解析（json.loads）が不要になり、
    # これまでのUnterminated string / Invalid escape 系のエラーが構造的に起きなくなる。
    result = tool_use_block.input
    return result, model
