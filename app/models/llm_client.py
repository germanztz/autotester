"""HTTP client for the Ollama chat completion API.

Used by the semantic segmenter to send text chunks to a local LLM.
Retry policy:
- Connection errors (server truly down): retried up to 3× with backoff.
- Timeouts (model loading / slow generation): NOT retried — failing fast
  gives the caller a clear signal to either wait or adjust the timeout.
- HTTP 5xx: retried up to 3× with backoff.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from app.utils.logging_setup import get_logger

logger = get_logger()


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama is not reachable or returns an error."""


_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0
_RETRYABLE_HTTP = {500, 502, 503, 504}


class OllamaChatClient:
    """HTTP client for Ollama chat completions (``/api/chat``).

    Features:
    - Connection pooling via a shared ``requests.Session``.
    - Retries transient failures (connection errors, 5xx) up to three
      times with exponential backoff.
    - Timeouts are NOT retried — they fail immediately so the caller
      can act (e.g. warm the model up or increase timeout).
    - ``is_available()`` probes ``/api/tags`` (lightweight).
    """

    def __init__(
        self,
        base_url: str = "http://dummy-server",
        timeout: float = 300.0,
        session: Any | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
        backoff_base: float = _BACKOFF_BASE_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self.max_attempts = max(1, max_attempts)
        self.backoff_base = backoff_base

    def _do(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        logger.debug("HTTP %s %s", method, path)
        try:
            response = self._session.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(f"Ollama unreachable at {self.base_url}") from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaUnavailable(
                f"Ollama request timed out after {self.timeout}s at {self.base_url}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> {type(exc).__name__}: {exc}"
            ) from exc

        if response.status_code in _RETRYABLE_HTTP:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise OllamaUnavailable(
                f"Ollama {method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
            )
        logger.debug("HTTP %s %s -> %s", method, path, response.status_code)
        return response

    def _is_retryable(self, exc: OllamaUnavailable) -> bool:
        """Return True only for connection-refused / transient 5xx errors.

        Timeouts are NOT retryable — if the first request timed out,
        retrying the same prompt with the same model will also time out.
        """
        msg = str(exc)
        if "unreachable" in msg:
            return True
        if any(f"HTTP {code}" in msg for code in _RETRYABLE_HTTP):
            return True
        return False

    def _do_with_retry(self, method: str, path: str, **kwargs: Any) -> Any:
        last_exc: OllamaUnavailable | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._do(method, path, **kwargs)
            except OllamaUnavailable as exc:
                last_exc = exc
                if not self._is_retryable(exc) or attempt >= self.max_attempts:
                    if attempt >= self.max_attempts and self._is_retryable(exc):
                        logger.warning(
                            "Ollama %s %s failed after %d attempts: %s",
                            method, path, self.max_attempts, exc,
                        )
                        raise OllamaUnavailable(
                            f"{exc} (after {self.max_attempts} attempts)"
                        ) from exc
                    raise
                logger.debug(
                    "Ollama %s %s attempt %d/%d failed: %s (retrying)",
                    method, path, attempt, self.max_attempts, exc,
                )
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        raise last_exc  # pragma: no cover

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and responds 200 to /api/tags."""
        try:
            self._do_with_retry("GET", "/api/tags")
            return True
        except OllamaUnavailable:
            return False

    def warmup(self, model: str) -> bool:
        """Pre-load the model into GPU memory with a trivial request.

        Sends a one-word chat prompt and waits for a response. This forces
        Ollama to fully load the model so that subsequent real chunk
        requests complete quickly.

        Returns True if the model responded, False on any error.
        """
        try:
            self.generate(model, "hello")
            return True
        except OllamaUnavailable:
            return False

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        format: str = "json",
        think: bool = False,
    ) -> str:
        """Send a chat prompt to the LLM and return the response text.

        Args:
            model: The Ollama model name.
            prompt: The user message content.
            system: Optional system message content.
            format: Output format (``"json"`` or ``""`` for plain text).
            think: Whether to enable reasoning tokens (deep‑seek style).

        Returns:
            The assistant's response as a plain string.

        Raises:
            OllamaUnavailable: If the API call fails after retries.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        total_chars = sum(len(m.get("content", "")) for m in messages)
        logger.info(
            "Ollama /api/chat | model=%s messages=%d total_chars=%d timeout=%s "
            "base_url=%s format=%s think=%s",
            model,
            len(messages),
            total_chars,
            self.timeout,
            self.base_url,
            format,
            think,
        )
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": think,
            "format": format,
        }
        response = self._do_with_retry(
            "POST",
            "/api/chat",
            json=body,
        )
        elapsed = response.elapsed.total_seconds() if hasattr(response, "elapsed") else 0
        logger.info(
            "Ollama /api/chat done | model=%s status=%d elapsed=%.1fs chars_in=%d",
            model,
            response.status_code,
            elapsed,
            total_chars,
        )
        data = response.json()
        if "message" not in data or "content" not in data["message"]:
            logger.debug("Ollama /api/chat response body: %s", data)
            raise OllamaUnavailable("Ollama /api/chat response missing 'message.content'")
        content = data["message"]["content"]
        if not content:
            logger.debug("Ollama /api/chat empty content, response body: %s", data)
        return content
