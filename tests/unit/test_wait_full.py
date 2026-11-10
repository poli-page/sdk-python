"""`R-WAIT-FULL` (SDK specification §9.4): a timeout never ends a wait early.

httpx, `asyncio.timeout` and the thread wait measure their delay on clocks that can be
coarser than `perf_counter` and fire a little early. These tests make the timeout fire at
once (a transport that raises `httpx.ReadTimeout` immediately, a stub deadline) and check
that the error still comes no sooner than the timeout after the wait started.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest

from poli_page import AsyncPoliPage, PoliPage, PoliPageError, RenderInput, _download

TIMEOUT = 0.15
INPUT: RenderInput = {"project": "p", "template": "t", "data": {}}
DESCRIPTOR: dict[str, Any] = {
    "documentId": "doc_1",
    "organizationId": "org_1",
    "environment": "sandbox",
    "format": "A4",
    "pageCount": 1,
    "sizeBytes": 300,
    "createdAt": "2026-01-01T00:00:00Z",
    "metadata": {},
    "presignedPdfUrl": "https://storage.test/doc_1.pdf",
    "expiresAt": "2026-01-01T00:15:00Z",
}
KEY = "pp_sandbox_00000000000000000000000000000000"


def _early_timeout(request: httpx.Request) -> httpx.Response:
    """Every request times out at once, as a timer that fired early would."""
    raise httpx.ReadTimeout("fired early", request=request)


def _download_early_timeout(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, json=DESCRIPTOR)
    raise httpx.ReadTimeout("fired early", request=request)


class _FirstChunkThenTimeout(httpx.SyncByteStream):
    """A body whose first chunk comes at once and whose next read times out at once."""

    def __iter__(self) -> Iterator[bytes]:
        yield b"%PDF-"
        raise httpx.ReadTimeout("fired early")


class _AsyncFirstChunkThenTimeout(httpx.AsyncByteStream):
    """The asyncio form of `_FirstChunkThenTimeout`."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"%PDF-"
        raise httpx.ReadTimeout("fired early")


def _later_chunk_timeout(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, json=DESCRIPTOR)
    return httpx.Response(200, stream=_FirstChunkThenTimeout())


def _async_later_chunk_timeout(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, json=DESCRIPTOR)
    return httpx.Response(200, stream=_AsyncFirstChunkThenTimeout())


def _deadline_expired(*_args: Any, **_kwargs: Any) -> Any:
    """Stands in for `_call_with_deadline` when `done.wait` returned before `seconds`."""
    raise _download._DeadlineExpired


def _early_asyncio_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `asyncio.timeout` fire before `seconds`, as asyncio does by up to a clock tick."""
    real_timeout = asyncio.timeout

    def early(_seconds: float | None) -> Any:
        return real_timeout(0.001)

    monkeypatch.setattr(asyncio, "timeout", early)


async def _hang(request: httpx.Request) -> httpx.Response:
    """The descriptor at once; storage never answers."""
    if request.method == "POST":
        return httpx.Response(200, json=DESCRIPTOR)
    await asyncio.sleep(5)
    return httpx.Response(200, content=b"")


def _sync(handler: Any) -> PoliPage:
    return PoliPage(
        api_key=KEY,
        max_retries=0,
        timeout=TIMEOUT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _async(handler: Any) -> AsyncPoliPage:
    return AsyncPoliPage(
        api_key=KEY,
        max_retries=0,
        timeout=TIMEOUT,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


class TestAttemptTimeout:
    def test_sync_attempt_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            _sync(_early_timeout).documents.get("doc_1")
        assert caught.value.code == "timeout"
        assert _ms(started) >= TIMEOUT * 1000

    async def test_async_attempt_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            await _async(_early_timeout).documents.get("doc_1")
        assert caught.value.code == "timeout"
        assert _ms(started) >= TIMEOUT * 1000


class TestDownloadTimeout:
    def test_sync_httpx_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            _sync(_download_early_timeout).render.pdf(INPUT)
        assert caught.value.code == "DOWNLOAD_FAILED"
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    async def test_async_httpx_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            await _async(_download_early_timeout).render.pdf(INPUT)
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    def test_sync_stream_idle_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with (
            pytest.raises(PoliPageError) as caught,
            _sync(_download_early_timeout).render.pdf_stream(INPUT),
        ):
            pass
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    def test_sync_deadline_is_not_reported_early(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The wait on the worker thread ended early (`done.wait` returned before `seconds`)."""
        monkeypatch.setattr(_download, "_call_with_deadline", _deadline_expired)
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            _sync(_download_early_timeout).render.pdf(INPUT)
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    async def test_async_deadline_is_not_reported_early(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`asyncio.timeout` fired before `seconds`, as asyncio does by up to a clock tick."""
        _early_asyncio_timeout(monkeypatch)
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            await _async(_hang).render.pdf(INPUT)
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000


class TestStreamTimeout:
    """`render.pdf_stream`: the wait for the first byte, then each later chunk on its own."""

    async def test_async_stream_httpx_timeout_is_not_reported_early(self) -> None:
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            async with _async(_download_early_timeout).render.pdf_stream(INPUT):
                pass
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    def test_sync_stream_deadline_is_not_reported_early(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wait for the headers and the first byte ended early on the worker thread."""
        monkeypatch.setattr(_download, "_call_with_deadline", _deadline_expired)
        started = time.perf_counter()
        with (
            pytest.raises(PoliPageError) as caught,
            _sync(_download_early_timeout).render.pdf_stream(INPUT),
        ):
            pass
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    async def test_async_stream_deadline_is_not_reported_early(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _early_asyncio_timeout(monkeypatch)
        started = time.perf_counter()
        with pytest.raises(PoliPageError) as caught:
            async with _async(_hang).render.pdf_stream(INPUT):
                pass
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    def test_sync_later_chunk_timeout_is_not_reported_early(self) -> None:
        with _sync(_later_chunk_timeout).render.pdf_stream(INPUT) as chunks:
            stream = iter(chunks)
            assert next(stream) == b"%PDF-"
            started = time.perf_counter()
            with pytest.raises(PoliPageError) as caught:
                next(stream)
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000

    async def test_async_later_chunk_timeout_is_not_reported_early(self) -> None:
        async with _async(_async_later_chunk_timeout).render.pdf_stream(INPUT) as chunks:
            stream = aiter(chunks)
            assert await anext(stream) == b"%PDF-"
            started = time.perf_counter()
            with pytest.raises(PoliPageError) as caught:
                await anext(stream)
        assert caught.value.message == "Failed to download PDF: timeout"
        assert _ms(started) >= TIMEOUT * 1000
