"""The presigned-URL download against a real local server: timeouts and short bodies.

`render.pdf` and `download_pdf()` bound the whole download by `timeout`; `render.pdf_stream`
bounds the wait for the answer and each gap between two chunks. Past it the error is
`DOWNLOAD_FAILED`, `Failed to download PDF: timeout`, no status, not retryable. A body that
ends short of its `Content-Length` is `Failed to download PDF: network error`.

The delays are short but far from the timeouts (a 50 ms gap under a 500 ms idle timeout), so
a slow runner does not flip a result. Each case runs with both clients. The late stream answer
needs its events in a set order, so that test drives a stub transport instead of the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from poli_page import AsyncPoliPage, PoliPage, PoliPageError

PDF = b"%PDF-1.4 " + b"x" * 291  # 300 bytes
INPUT: dict[str, Any] = {"project": "p", "template": "t", "data": {}}


class PdfServer:
    """Answers `POST /v1/render` with a descriptor and `GET /pdf` the way `mode` says.

    Modes: `ok`, `hang` (no answer), `trickle` (the PDF in 30 chunks, 50 ms apart),
    `first-byte-stall` (headers after `header_delay`, then no body byte), `first-byte-late`
    (headers after `header_delay`, the first chunk `header_delay` later, then the rest),
    `stall` (headers and one chunk, then nothing), `short` (10 of the 300 announced bytes,
    then the connection closes), `trickle-drop` (chunks 50 ms apart for 600 ms, then the
    connection closes).
    """

    def __init__(self) -> None:
        self.mode = "ok"
        self.header_delay = 0.0
        self.release = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                body = json.dumps(_descriptor(f"{server.origin}/pdf")).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                with contextlib.suppress(OSError):
                    server.answer_pdf(self)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()

    def answer_pdf(self, handler: BaseHTTPRequestHandler) -> None:
        if self.mode == "hang":
            self.release.wait(10)
            handler.close_connection = True
            return
        if self.mode in ("first-byte-stall", "first-byte-late"):
            time.sleep(self.header_delay)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/pdf")
        handler.send_header("Content-Length", str(len(PDF)))
        handler.end_headers()
        handler.wfile.flush()
        if self.mode == "ok":
            handler.wfile.write(PDF)
        elif self.mode == "trickle":
            for i in range(0, len(PDF), 10):
                handler.wfile.write(PDF[i : i + 10])
                handler.wfile.flush()
                time.sleep(0.05)
        elif self.mode == "stall":
            handler.wfile.write(PDF[:10])
            handler.wfile.flush()
            self.release.wait(10)
            handler.close_connection = True
        elif self.mode == "short":
            handler.wfile.write(PDF[:10])
            handler.wfile.flush()
            handler.close_connection = True
        elif self.mode == "first-byte-stall":
            # Headers at `header_delay`, then no body byte.
            self.release.wait(10)
            handler.close_connection = True
        elif self.mode == "first-byte-late":
            # Headers at `header_delay`, the first chunk `header_delay` later, then the rest.
            time.sleep(self.header_delay)
            for i in range(0, len(PDF), 100):
                handler.wfile.write(PDF[i : i + 100])
                handler.wfile.flush()
                time.sleep(0.05)
        elif self.mode == "trickle-drop":
            for i in range(0, 120, 10):
                handler.wfile.write(PDF[i : i + 10])
                handler.wfile.flush()
                time.sleep(0.05)
            handler.close_connection = True
        else:
            raise AssertionError(f"unknown mode {self.mode}")

    def close(self) -> None:
        self.release.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()


def _descriptor(url: str) -> dict[str, Any]:
    return {
        "documentId": "doc_1",
        "organizationId": "org_1",
        "environment": "sandbox",
        "format": "A4",
        "pageCount": 1,
        "sizeBytes": len(PDF),
        "createdAt": "2026-01-01T00:00:00Z",
        "metadata": {},
        "presignedPdfUrl": url,
        "expiresAt": "2026-01-01T00:15:00Z",
    }


@pytest.fixture
def server() -> Iterator[PdfServer]:
    srv = PdfServer()
    yield srv
    srv.close()


def _sync(server: PdfServer, method: str, timeout: float, call_timeout: float | None) -> bytes:
    render_input: dict[str, Any] = dict(INPUT)
    if call_timeout is not None:
        render_input["timeout"] = call_timeout
    with PoliPage(api_key="pp_sandbox_x", base_url=server.origin, timeout=timeout) as client:
        if method == "render.pdf":
            return client.render.pdf(render_input)  # type: ignore[arg-type]
        if method == "download_pdf":
            return client.render.document(render_input).download_pdf()  # type: ignore[arg-type]
        with client.render.pdf_stream(render_input) as chunks:  # type: ignore[arg-type]
            return b"".join(chunks)


async def _async(
    server: PdfServer, method: str, timeout: float, call_timeout: float | None
) -> bytes:
    render_input: dict[str, Any] = dict(INPUT)
    if call_timeout is not None:
        render_input["timeout"] = call_timeout
    async with AsyncPoliPage(
        api_key="pp_sandbox_x", base_url=server.origin, timeout=timeout
    ) as client:
        if method == "render.pdf":
            return await client.render.pdf(render_input)  # type: ignore[arg-type]
        if method == "download_pdf":
            doc = await client.render.document(render_input)  # type: ignore[arg-type]
            return await doc.download_pdf()
        async with client.render.pdf_stream(render_input) as chunks:  # type: ignore[arg-type]
            return b"".join([chunk async for chunk in chunks])


def _call(
    flavor: str,
    server: PdfServer,
    method: str,
    timeout: float,
    call_timeout: float | None = None,
) -> bytes:
    if flavor == "sync":
        return _sync(server, method, timeout, call_timeout)
    return asyncio.run(_async(server, method, timeout, call_timeout))


def _assert_timeout(err: PoliPageError) -> None:
    assert err.code == "DOWNLOAD_FAILED"
    assert err.message == "Failed to download PDF: timeout"
    assert err.status is None
    assert err.request_id is None
    assert err.is_retryable() is False
    assert err.is_network_error() is False


def _assert_network(err: PoliPageError) -> None:
    assert err.code == "DOWNLOAD_FAILED"
    assert err.message == "Failed to download PDF: network error"
    assert err.status is None
    assert err.is_retryable() is False


FLAVORS = ["sync", "async"]
ALL_METHODS = ["render.pdf", "download_pdf", "render.pdf_stream"]
WHOLE_METHODS = ["render.pdf", "download_pdf"]


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_download_that_works_returns_the_pdf(server: PdfServer, flavor: str, method: str) -> None:
    assert _call(flavor, server, method, timeout=5) == PDF


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_no_answer_times_out(server: PdfServer, flavor: str, method: str) -> None:
    server.mode = "hang"
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, method, timeout=0.3)
    _assert_timeout(excinfo.value)


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("method", WHOLE_METHODS)
def test_the_timeout_bounds_the_whole_download(server: PdfServer, flavor: str, method: str) -> None:
    # Every gap (50 ms) is far below the timeout; the whole body (1.5 s) is not.
    server.mode = "trickle"
    started = time.perf_counter()
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, method, timeout=0.5)
    _assert_timeout(excinfo.value)
    assert time.perf_counter() - started < 1.4, "the call waited for the whole body"


@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_stream_timeout_is_an_idle_timeout(server: PdfServer, flavor: str) -> None:
    server.mode = "trickle"
    assert _call(flavor, server, "render.pdf_stream", timeout=0.5) == PDF


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_stream_that_stalls_mid_body_times_out(server: PdfServer, flavor: str) -> None:
    server.mode = "stall"
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, "render.pdf_stream", timeout=0.3)
    _assert_timeout(excinfo.value)


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_stream_dropped_after_its_timeout_is_not_a_timeout(
    server: PdfServer, flavor: str
) -> None:
    # 600 ms of chunks 50 ms apart, then a dropped connection: longer than the 300 ms timeout
    # in all, but the idle timeout never fired, so the error is the network one.
    server.mode = "trickle-drop"
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, "render.pdf_stream", timeout=0.3)
    _assert_network(excinfo.value)


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("method", WHOLE_METHODS)
def test_the_call_timeout_bounds_the_download(server: PdfServer, flavor: str, method: str) -> None:
    server.mode = "trickle"
    if method == "download_pdf":
        # `download_pdf()` takes no timeout: the client's applies.
        assert _call(flavor, server, method, timeout=5, call_timeout=0.5) == PDF
        return
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, method, timeout=5, call_timeout=0.5)
    _assert_timeout(excinfo.value)


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_body_short_of_its_content_length_fails(
    server: PdfServer, flavor: str, method: str
) -> None:
    server.mode = "short"
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, method, timeout=5)
    _assert_network(excinfo.value)


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_stream_whose_first_byte_stalls_times_out(server: PdfServer, flavor: str) -> None:
    # The headers come at once, then no body byte: the call fails at about `timeout`.
    server.mode = "first-byte-stall"
    started = time.perf_counter()
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, "render.pdf_stream", timeout=0.5)
    _assert_timeout(excinfo.value)
    assert time.perf_counter() - started < 0.9


@pytest.mark.parametrize("flavor", FLAVORS)
def test_headers_and_first_byte_share_one_timeout(server: PdfServer, flavor: str) -> None:
    # Headers after 600 ms of a 1 s timeout, then no body byte. The first byte is due 1 s after
    # the request started, not 1 s after the headers (which would end the call at 1.6 s).
    server.mode = "first-byte-stall"
    server.header_delay = 0.6
    started = time.perf_counter()
    with pytest.raises(PoliPageError) as excinfo:
        _call(flavor, server, "render.pdf_stream", timeout=1.0)
    _assert_timeout(excinfo.value)
    assert time.perf_counter() - started < 1.4


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_first_byte_within_the_timeout_streams(server: PdfServer, flavor: str) -> None:
    # Headers after 300 ms, the first chunk 300 ms later: 600 ms in all, under the 1 s timeout.
    server.mode = "first-byte-late"
    server.header_delay = 0.3
    assert _call(flavor, server, "render.pdf_stream", timeout=1.0) == PDF


class _FirstChunkOnRelease(httpx.SyncByteStream):
    """A body whose first chunk waits for `release`: the headers come at once, the bytes late.

    `reading` is set once the worker waits for that chunk.
    """

    def __init__(self) -> None:
        self.reading = threading.Event()
        self.release = threading.Event()

    def __iter__(self) -> Iterator[bytes]:
        self.reading.set()
        if not self.release.wait(5):
            raise AssertionError("the test never released the first chunk")
        yield PDF


def test_a_stream_answer_after_the_deadline_is_closed() -> None:
    # The headers come at once and the first chunk only once the call has failed, so the
    # worker gets its answer after the deadline. The late answer is closed, not leaked.
    # A stub transport, not the local server: no httpx timeout races the deadline, and the
    # first chunk comes when the test says, not after a sleep.
    pdf_url = "https://storage.test/doc_1.pdf"
    body = _FirstChunkOnRelease()

    def handler(request: httpx.Request) -> httpx.Response:
        # `request=` so that `close` can tell the storage answer even when httpx closes a
        # response as it builds it (a JSON body is read at once).
        if request.method == "POST":
            return httpx.Response(200, json=_descriptor(pdf_url), request=request)
        return httpx.Response(200, stream=body, request=request)

    closed: list[httpx.Response] = []
    real_close = httpx.Response.close

    def close(response: httpx.Response) -> None:
        if str(response.request.url) == pdf_url:
            closed.append(response)
        real_close(response)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http_client,
        pytest.MonkeyPatch.context() as patch,
        PoliPage(api_key="pp_sandbox_x", timeout=0.5, http_client=http_client) as client,
    ):
        patch.setattr(httpx.Response, "close", close)
        try:
            with pytest.raises(PoliPageError) as excinfo:
                client.render.pdf_stream(INPUT).__enter__()  # type: ignore[arg-type]
            _assert_timeout(excinfo.value)
            assert closed == [], "the answer was closed before it came"
        finally:
            body.release.set()
        workers = [t for t in threading.enumerate() if t.name == "poli-page-download"]
        for worker in workers:
            worker.join(5)
        assert not any(worker.is_alive() for worker in workers)
    # The worker was waiting for the first chunk when the call gave up: the headers had come.
    assert body.reading.is_set(), "the worker never reached the first chunk before the deadline"
    assert len(closed) == 1
    assert closed[0].is_closed
