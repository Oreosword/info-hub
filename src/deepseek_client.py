import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

import database as db


class DeepSeekError(Exception):
    pass


@dataclass
class DeepSeekResponse:
    model: str
    content: str
    raw: Dict[str, Any]


class DeepSeekClient:
    def __init__(self, settings: db.DeepSeekSettings, timeout: int = 40):
        self.settings = settings
        self.timeout = timeout
        self.base_url = (settings.base_url or db.DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")

    def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        response_json: bool = False,
        thinking: str = "disabled",
        reasoning_effort: Optional[str] = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> DeepSeekResponse:
        if not self.settings.api_key:
            raise DeepSeekError("未配置 DeepSeek API key")
        payload: Dict[str, Any] = {
            "model": model or self.settings.analysis_model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking": {"type": thinking},
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DeepSeekError(f"DeepSeek 连接失败：{exc}") from exc

        if response.status_code >= 400:
            detail = _extract_error(response)
            raise DeepSeekError(f"DeepSeek 返回 {response.status_code}：{detail}")

        try:
            data = response.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek 响应格式无法解析") from exc

        if not content:
            raise DeepSeekError("DeepSeek 响应为空")
        return DeepSeekResponse(model=data.get("model") or payload["model"], content=content, raw=data)


def parse_json_content(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek JSON 输出不完整或格式错误") from exc
    if not isinstance(data, dict):
        raise DeepSeekError("DeepSeek JSON 输出不是对象")
    return data


def _extract_error(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error)
            return str(data.get("message") or data)
    except ValueError:
        pass
    return response.text[:300]
