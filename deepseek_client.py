"""
DeepSeek API client for stock analysis workflows.

Usage:
  $env:DEEPSEEK_API_KEY="your-api-key"
  python deepseek_client.py --test
  python deepseek_client.py "总结一下贵州茅台的核心看点"
  python deepseek_client.py "基于数据给出分析提纲" --stock-data output/data_600519.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def load_env_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from .env without adding a dependency."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_stock_context(path: str, max_chars: int = 12000) -> str:
    """Create a compact prompt context from a collected stock JSON file."""
    data_path = Path(path)
    data = json.loads(data_path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        overview: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, list):
                overview[key] = {
                    "type": "list",
                    "count": len(value),
                    "sample": value[:2],
                }
            elif isinstance(value, dict):
                overview[key] = {
                    "type": "object",
                    "keys": list(value.keys())[:30],
                    "sample": dict(list(value.items())[:10]),
                }
            else:
                overview[key] = value
        text = json.dumps(overview, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)

    if len(text) > max_chars:
        return text[:max_chars] + "\n...（数据已截断，仅用于生成分析提纲）"
    return text


def deepseek_chat(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY. Set it in your shell or local .env file.")

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"DeepSeek API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API request failed: {exc.reason}") from exc

    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected DeepSeek response: {result}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Call DeepSeek for stock analysis prompts.")
    parser.add_argument("prompt", nargs="?", help="User prompt for DeepSeek.")
    parser.add_argument("--stock-data", help="Path to output/data_*.json to include as context.")
    parser.add_argument("--system", default="你是严谨的A股研究助手，只提供研究框架和风险提示，不构成投资建议。")
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--output", help="Write the response to a markdown file.")
    parser.add_argument("--test", action="store_true", help="Run a small connectivity test.")
    args = parser.parse_args()

    load_env_file()

    prompt = args.prompt
    if args.test:
        prompt = "请用一句中文回复：DeepSeek 接入成功。"
    if not prompt:
        parser.error("prompt is required unless --test is used")

    if args.stock_data:
        context = build_stock_context(args.stock_data)
        prompt = f"下面是个股数据摘要，请结合数据回答用户问题。\n\n数据摘要：\n{context}\n\n用户问题：\n{prompt}"

    content = deepseek_chat(
        [
            {"role": "system", "content": args.system},
            {"role": "user", "content": prompt},
        ],
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        base_url=args.base_url,
    )

    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"[OK] DeepSeek response written to {args.output}")
    else:
        print(content)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[X] {exc}", file=sys.stderr)
        raise SystemExit(1)
