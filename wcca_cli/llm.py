from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import read_yaml


@dataclass(frozen=True)
class LLMResult:
    provider: str
    status: str
    text: str
    error: str | None = None


def load_llm_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"provider": "none"}
    config = read_yaml(path)
    config.setdefault("provider", "none")
    return _expand_env(config)


def generate_text(prompt: str, config: dict[str, Any] | None = None) -> LLMResult:
    llm_config = config or {"provider": "none"}
    provider = str(llm_config.get("provider", "none")).lower()
    if provider == "none":
        return LLMResult(provider="none", status="skipped", text="")
    if provider in {"openai_compatible", "openai-compatible"}:
        return _generate_openai_compatible(prompt, llm_config)
    if provider in {"command", "claude_cli", "claude-cli"}:
        return _generate_command(prompt, llm_config)
    return LLMResult(provider=provider, status="failed", text="", error=f"Unsupported LLM provider: {provider}")


def _generate_openai_compatible(prompt: str, config: dict[str, Any]) -> LLMResult:
    base_url = str(config.get("base_url", "")).rstrip("/")
    model = config.get("model")
    if not base_url or not model:
        return LLMResult("openai_compatible", "failed", "", "base_url and model are required")
    endpoint = str(config.get("endpoint", "/v1/chat/completions")).lstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": config.get("system_prompt", _default_system_prompt())},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(config.get("temperature", 0.2)),
    }
    payload.update(config.get("payload", {}))
    headers = {"Content-Type": "application/json"}
    api_key = config.get("api_key")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout_seconds", 60))) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return LLMResult("openai_compatible", "failed", "", str(exc))
    text = _extract_openai_text(data)
    return LLMResult("openai_compatible", "completed" if text else "failed", text, None if text else "empty response")


def _generate_command(prompt: str, config: dict[str, Any]) -> LLMResult:
    executable = config.get("executable", "claude")
    args = config.get("args", [])
    if not isinstance(args, list):
        return LLMResult("command", "failed", "", "args must be a list")
    command = [str(executable), *[str(item) for item in args]]
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=float(config.get("timeout_seconds", 120)),
            cwd=config.get("working_dir") or None,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LLMResult("command", "failed", "", str(exc))
    provider = str(config.get("provider", "command"))
    if completed.returncode != 0:
        return LLMResult(provider, "failed", completed.stdout.strip(), completed.stderr.strip())
    return LLMResult(provider, "completed", completed.stdout.strip())


def _extract_openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(first.get("text") or "")


def _expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str) and value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


def _default_system_prompt() -> str:
    return (
        "You are a WCCA engineering assistant. Only provide review suggestions and narrative drafts. "
        "Do not invent critical parameters, approve risks, or change pass/fail conclusions."
    )
