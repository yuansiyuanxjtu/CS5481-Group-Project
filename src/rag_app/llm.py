"""One bounded Chat Completions request; no hidden retries or external tools."""
import asyncio
import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


class GenerationError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport

    def generate(self, messages: list[dict]) -> dict:
        try:
            return asyncio.run(asyncio.wait_for(self._request(messages), timeout=self.settings.timeout))
        except TimeoutError:
            raise LLMError("LLM request exceeded the total time limit. This is a service failure, not missing knowledge.") from None

    async def _request(self, messages: list[dict]) -> dict:
        cfg = self.settings
        if not cfg.api_key:
            raise LLMError("Set LLM_API_KEY in the local .env file before submitting a question.")
        payload = {"model": cfg.model, "messages": messages, "max_tokens": cfg.max_tokens,
                   "temperature": 0, "stream": False}
        if cfg.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if cfg.thinking:
            payload["thinking"] = {"type": cfg.thinking}
        # Never expose provider response bodies, exceptions or authorization headers.
        try:
            async with httpx.AsyncClient(timeout=cfg.timeout, follow_redirects=False, transport=self.transport) as client:
                response = await client.post(cfg.base_url.rstrip("/") + "/chat/completions",
                                       headers={"Authorization": f"Bearer {cfg.api_key}"}, json=payload)
            if response.status_code != 200:
                raise LLMError(f"LLM service returned HTTP {response.status_code}; check credentials, quota and endpoint.")
            body = response.json()
            choice = body["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise GenerationError("LLM output was truncated or did not finish normally. No answer was accepted.")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > 50000:
                raise GenerationError("LLM returned empty or oversized content.")
            return {"content": content, "model": body.get("model", cfg.model),
                    "usage": body.get("usage", {})}
        except httpx.TimeoutException:
            raise LLMError("LLM request timed out. This is a service failure, not missing knowledge.") from None
        except httpx.HTTPError:
            raise LLMError("Unable to contact the LLM service. Check network and endpoint.") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise GenerationError("LLM service returned an invalid response format.") from None
