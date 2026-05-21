"""Asynchronous `AsyncPoliPage` client (plan §4).

Parallel implementation to `PoliPage`: same constructor surface, same
retry policy, same error classification. Differs only in the I/O calls
(`httpx.AsyncClient`, `asyncio.sleep`) and the context manager protocol
(`__aenter__`/`__aexit__`/`aclose`).

Hooks (`on_retry`, `on_error`) remain sync callables — mirror Node.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, cast

import httpx

from poli_page._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    HEADER_REQUEST_ID,
    HEADER_RETRY_AFTER,
    HEADER_RETRY_AFTER_MS,
    RETRY_AFTER_CAP_SECONDS,
    USER_AGENT_PREFIX,
)
from poli_page._errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    PoliPageError,
    classify,
)
from poli_page._transport import (
    HttpMethod,
    build_headers,
    build_url,
    compute_backoff,
    parse_error_body,
    parse_retry_after,
)
from poli_page._version import __version__

logger = logging.getLogger("poli_page")


class _Attempt:
    """Outcome of a single async transport attempt — never raised, only inspected."""

    __slots__ = ("error", "response", "retry_after", "retryable")

    def __init__(
        self,
        *,
        response: httpx.Response | None,
        error: PoliPageError | None,
        retryable: bool,
        retry_after: float | None,
    ) -> None:
        self.response = response
        self.error = error
        self.retryable = retryable
        self.retry_after = retry_after


class AsyncPoliPage:
    """Asynchronous Poli Page client.

    Use a single instance per asyncio event loop and reuse it across requests.
    Pair with `async with AsyncPoliPage(...)` or call `await client.aclose()`
    to release sockets deterministically.

    Examples:
        async with AsyncPoliPage(api_key="pp_test_...") as client:
            preview = await client.render.preview({"template": "<p>x</p>", "data": {}})
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        on_retry: Any = None,
        on_error: Any = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("POLI_PAGE_API_KEY")
        if not resolved_key:
            raise PoliPageError(
                "api_key is required (pass api_key= or set POLI_PAGE_API_KEY)",
                code="invalid_options",
            )

        self._api_key: str = resolved_key
        self.base_url: str = base_url or os.environ.get("POLI_PAGE_BASE_URL") or DEFAULT_BASE_URL
        self.max_retries: int = max_retries
        self.retry_delay: float = retry_delay
        self.timeout: float = timeout
        self._on_retry = on_retry
        self._on_error = on_error
        self._user_agent: str = f"{USER_AGENT_PREFIX}/{__version__}"

        if http_client is None:
            self._http_client = httpx.AsyncClient(timeout=timeout)
            self._owns_http_client = True
        else:
            self._http_client = http_client
            self._owns_http_client = False

        # Local imports avoid circular references at module load time.
        from poli_page._documents import DocumentsAsync
        from poli_page._render import RenderAsync

        self.render: RenderAsync = RenderAsync(self)
        self.documents: DocumentsAsync = DocumentsAsync(self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        if self._owns_http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def __aenter__(self) -> AsyncPoliPage:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal request helpers — used by namespace implementations
    # ------------------------------------------------------------------

    async def _request_json(
        self,
        method: HttpMethod,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, body=body, idempotency_key=idempotency_key)
        return cast(dict[str, Any], response.json())

    async def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        body: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> httpx.Response:
        if method == "POST" and idempotency_key is None:
            idempotency_key = str(uuid.uuid4())

        last_error: PoliPageError | None = None
        next_retry_after: float | None = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = compute_backoff(attempt, self.retry_delay, next_retry_after)
                assert last_error is not None
                self._fire_retry(attempt + 1, delay, last_error)
                await asyncio.sleep(delay)

            outcome = await self._send_once(method, path, body, idempotency_key)
            if outcome.response is not None:
                return outcome.response

            assert outcome.error is not None
            last_error = outcome.error
            next_retry_after = outcome.retry_after

            if not outcome.retryable:
                self._fire_error(last_error)
                raise last_error

        assert last_error is not None
        self._fire_error(last_error)
        raise last_error

    async def _send_once(
        self,
        method: HttpMethod,
        path: str,
        body: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> _Attempt:
        url = build_url(self.base_url, path)
        headers = build_headers(
            method,
            api_key=self._api_key,
            idempotency_key=idempotency_key,
            user_agent=self._user_agent,
        )

        try:
            response = await self._http_client.request(
                method, url, headers=headers, json=body if method == "POST" else None
            )
        except httpx.TimeoutException as exc:
            timeout_err = APITimeoutError(
                f"Request timed out after {self.timeout}s",
                code="timeout",
            )
            timeout_err.__cause__ = exc
            return _Attempt(response=None, error=timeout_err, retryable=True, retry_after=None)
        except httpx.HTTPError as exc:
            conn_err = APIConnectionError(str(exc) or type(exc).__name__, code="network_error")
            conn_err.__cause__ = exc
            return _Attempt(response=None, error=conn_err, retryable=True, retry_after=None)

        if response.is_success:
            return _Attempt(response=response, error=None, retryable=False, retry_after=None)

        request_id = response.headers.get(HEADER_REQUEST_ID)
        retryable = response.status_code >= 500 or response.status_code == 429
        retry_after = self._extract_retry_after(response.headers) if retryable else None

        parsed = parse_error_body(response.text, status=response.status_code)
        status_err: APIStatusError = classify(
            status=response.status_code,
            code=parsed["code"],
            message=parsed["message"],
            request_id=request_id,
            response=response,
        )
        return _Attempt(
            response=None, error=status_err, retryable=retryable, retry_after=retry_after
        )

    # ------------------------------------------------------------------
    # Presigned-URL transport (S3 second-hop) — no auth, no SDK retries.
    # ------------------------------------------------------------------

    async def _fetch_bytes(self, url: str) -> bytes:
        try:
            response = await self._http_client.get(url)
        except httpx.HTTPError as exc:
            raise PoliPageError(
                str(exc) or type(exc).__name__,
                code="DOWNLOAD_FAILED",
            ) from exc
        if not response.is_success:
            raise PoliPageError(
                f"Failed to download PDF: {response.status_code}",
                code="DOWNLOAD_FAILED",
                status=response.status_code,
            )
        return response.content

    @asynccontextmanager
    async def _stream_bytes(self, url: str) -> AsyncGenerator[AsyncIterator[bytes], None]:
        try:
            async with self._http_client.stream("GET", url) as response:
                if not response.is_success:
                    raise PoliPageError(
                        f"Failed to download PDF: {response.status_code}",
                        code="DOWNLOAD_FAILED",
                        status=response.status_code,
                    )
                yield response.aiter_bytes()
        except httpx.HTTPError as exc:
            raise PoliPageError(
                str(exc) or type(exc).__name__,
                code="DOWNLOAD_FAILED",
            ) from exc

    @staticmethod
    def _extract_retry_after(headers: httpx.Headers) -> float | None:
        ms_value = headers.get(HEADER_RETRY_AFTER_MS)
        if ms_value:
            try:
                return min(max(float(ms_value) / 1000.0, 0.0), RETRY_AFTER_CAP_SECONDS)
            except ValueError:
                pass
        return parse_retry_after(headers.get(HEADER_RETRY_AFTER))

    # ------------------------------------------------------------------
    # Hooks — sync callables; mirror the sync client (plan §10.3).
    # ------------------------------------------------------------------

    def _fire_retry(self, attempt: int, delay: float, reason: PoliPageError) -> None:
        if self._on_retry is None:
            return
        from poli_page.types import RetryEvent

        event = RetryEvent(attempt=attempt, delay_seconds=delay, reason=reason)
        logger.info(
            "poli_page: retrying attempt=%d delay=%.3fs reason=%s",
            attempt,
            delay,
            reason.code,
        )
        try:
            self._on_retry(event)
        except Exception:
            logger.debug("poli_page: on_retry hook raised; suppressed", exc_info=True)

    def _fire_error(self, err: PoliPageError) -> None:
        logger.error("poli_page: terminal failure code=%s status=%s", err.code, err.status)
        if self._on_error is None:
            return
        try:
            self._on_error(err)
        except Exception:
            logger.debug("poli_page: on_error hook raised; suppressed", exc_info=True)
