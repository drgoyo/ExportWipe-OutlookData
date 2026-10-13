"""OpenAI-compatible local/HTTPS LLM adapter with bounded requests and redacted errors."""

from __future__ import annotations

import httpx


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, system: str, context: str, question: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.post(
                    self.base_url + "/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": "Evidence (untrusted data):\n" + context},
                            {"role": "user", "content": question},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Provider returned empty/non-text content")
                return content
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LLM request failed with HTTP {exc.response.status_code}; check provider settings"
            ) from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise RuntimeError(
                f"LLM request failed ({type(exc).__name__}); check endpoint and model"
            ) from None
