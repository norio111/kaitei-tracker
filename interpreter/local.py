"""
Ollamaバックエンド。llm.get_backend('ollama') 経由で使う。

想定運用：
  - RTX 4070 Super (12GB VRAM) では、7B〜14B級の量子化モデルが現実的
    （例: qwen2.5:14b-instruct-q4, gemma2:9b 等）
  - 本タスクは自由創作ではなく「本文からの構造化抽出」なので、
    一般的な会話性能よりJSON追従性・指示追従性を重視してモデルを選ぶとよい
  - Ollamaを事前に起動しておくこと: `ollama serve`（デフォルトで localhost:11434）
"""

import json

import requests

from interpreter.llm import FREEFORM_JSON_INSTRUCTIONS, SYSTEM_PROMPT, build_user_message, parse_json_response

DEFAULT_MODEL = "qwen2.5:14b-instruct"
DEFAULT_HOST = "http://localhost:11434"


def interpret(
    title: str,
    prompt_text: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
) -> tuple[dict, str]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + FREEFORM_JSON_INSTRUCTIONS},
            {"role": "user", "content": build_user_message(title, prompt_text)},
        ],
        "format": "json",  # Ollama側でJSON出力を強制（対応モデルのみ有効）
        "stream": False,
        "options": {"num_predict": 8192},  # 長い応答が途中で切れないよう余裕を持たせる
    }
    res = requests.post(f"{host}/api/chat", json=payload, timeout=300)
    res.raise_for_status()
    data = res.json()
    raw_text = data["message"]["content"]

    try:
        result = parse_json_response(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON解析失敗: {e}\n--- 生レスポンス（先頭800字） ---\n{raw_text[:800]}") from e

    return result, model
