import json
from typing import Any

import httpx


class LLMRequestError(RuntimeError):
    pass


class LLMInvalidResponse(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 120,
        max_output_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        if base.endswith(("/v1", "/api/paas/v4")):
            self._endpoint = f"{base}/chat/completions"
        else:
            self._endpoint = f"{base}/v1/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_output_tokens = max_output_tokens
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._model

    async def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request_body = {
            "model": self._model,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "max_tokens": self._max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }

        response: httpx.Response | None = None
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
            for attempt in range(2):
                try:
                    response = await client.post(self._endpoint, headers=headers, json=request_body)
                    break
                except httpx.RequestError as exc:
                    if attempt == 1:
                        raise LLMRequestError(f"模型网关连接失败: {type(exc).__name__}") from exc

        assert response is not None
        if response.is_error:
            raise LLMRequestError(f"模型网关返回 HTTP {response.status_code}")
        try:
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
            decoded = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMInvalidResponse("模型响应不是有效的 JSON 对象") from exc
        if not isinstance(decoded, dict):
            raise LLMInvalidResponse("模型响应 JSON 顶层必须是对象")
        return decoded
