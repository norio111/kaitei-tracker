"""Claude APIバックエンド。llm.get_backend('claude') 経由で使う。"""

import json
import os

from interpreter.llm import SYSTEM_PROMPT, build_user_message, parse_json_response

DEFAULT_MODEL = "claude-sonnet-4-6"


def interpret(title: str, prompt_text: str, model: str = DEFAULT_MODEL, api_key: str | None = None) -> tuple[dict, str]:
    import anthropic

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,  # change_pointsが多い資料でも途中で切れないよう余裕を持たせる
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(title, prompt_text)}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")

    try:
        result = parse_json_response(raw_text)
    except json.JSONDecodeError as e:
        # JSON解析に失敗した場合、原因調査ができるよう生レスポンスをエラーメッセージに含める
        raise RuntimeError(
            f"JSON解析失敗: {e}\n"
            f"stop_reason={response.stop_reason}\n"
            f"--- 生レスポンス（先頭800字） ---\n{raw_text[:800]}"
        ) from e

    return result, model
