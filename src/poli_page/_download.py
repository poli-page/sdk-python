"""The presigned-URL download: a plain GET to object storage, no auth, no retry.

The download is bounded by the client's `timeout` (or the render call's own `timeout`), the
same value as an API attempt:

- `render.pdf` and `download_pdf()` bound the whole download, body included. httpx has no
  total timeout, so the sync client runs the download on a worker thread and stops waiting
  when the time is up; the async client wraps it in `asyncio.timeout`.
- `render.pdf_stream` bounds the wait for the first byte and each gap between two chunks (an
  idle timeout), not the total, so a large PDF read at the caller's pace is not cut off. The
  answer's headers and the first chunk share one budget, measured from the start of the
  request and enforced the same way as a whole download; each later chunk is bounded by
  httpx's read timeout.

A failure is `DOWNLOAD_FAILED`: `Failed to download PDF: HTTP <status>` with the storage
status, `Failed to download PDF: timeout` when the timeout fired (httpx's own timeout
exceptions, or the deadline above), and `Failed to download PDF: network error` for any other
transport failure, a connection that closes before the announced `Content-Length` included.

A `timeout` of 0 or less sets no deadline: it goes to httpx as it is, as for an API attempt,
and httpx decides what it means.

The sync worker cannot be interrupted: httpx's sync transport has no cancellation, and the
read timeout of a body is set once for the whole read. After the caller's deadline the
worker stops at its next step (before the request, after the headers, after a chunk), but
until then it keeps one pooled connection busy, until its current httpx phase ends: at most
one per-operation `timeout` for each phase still under way (the pool wait, the connection,
the request, a read).
"""

from __future__ import annotations

import asyncio
import contextvars
import itertools
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TypeVar

import httpx

from poli_page._constants import MESSAGE_DOWNLOAD_FAILED_TIMEOUT
from poli_page._errors import PoliPageError
from poli_page._transport import download_failed_message

_T = TypeVar("_T")

_DOWNLOAD_FAILED = "DOWNLOAD_FAILED"


def _failed(status: int | None = None) -> PoliPageError:
    """`DOWNLOAD_FAILED` with the storage status, or the network error without one."""
    return PoliPageError(download_failed_message(status), code=_DOWNLOAD_FAILED, status=status)


def _timed_out() -> PoliPageError:
    return PoliPageError(MESSAGE_DOWNLOAD_FAILED_TIMEOUT, code=_DOWNLOAD_FAILED)


def _from_httpx(exc: httpx.HTTPError) -> PoliPageError:
    """An httpx timeout exception is the timeout; any other transport failure, the network one."""
    return _timed_out() if isinstance(exc, httpx.TimeoutException) else _failed()


# ---------------------------------------------------------------------------
# Sync: a deadline enforced by waiting on a worker thread
# ---------------------------------------------------------------------------


class _DeadlineExpired(Exception):
    """The caller stopped waiting for the worker: the timeout fired."""


def _call_with_deadline(
    fn: Callable[[threading.Event], _T],
    seconds: float,
    discard: Callable[[_T], None] | None = None,
) -> _T:
    """Run `fn` on a worker thread and wait at most `seconds` for its result.

    Raises `_DeadlineExpired` when the wait ends first. `fn` then sees its event set and
    should stop early; a value it still returns goes to `discard` (to close a response).
    The worker runs in a copy of the caller's context, so context variables (tracing)
    follow it.
    """
    abandoned = threading.Event()
    done = threading.Event()
    lock = threading.Lock()
    outcome: list[_T] = []
    failure: list[BaseException] = []

    def work() -> None:
        try:
            value = fn(abandoned)
        except BaseException as exc:  # handed to the caller, which raises it: never swallowed
            with lock:
                failure.append(exc)
        else:
            with lock:
                late = abandoned.is_set()
                if not late:
                    outcome.append(value)
            if late and discard is not None:
                discard(value)
        finally:
            done.set()

    context = contextvars.copy_context()
    worker = threading.Thread(
        target=context.run, args=(work,), name="poli-page-download", daemon=True
    )
    worker.start()
    try:
        done.wait(seconds)
    finally:
        with lock:
            # Give up on the worker unless it has already stored its outcome. Also when the
            # wait itself raised (a KeyboardInterrupt in the caller).
            if not outcome and not failure:
                abandoned.set()
    if failure:
        raise failure[0]
    if outcome:
        return outcome[0]
    raise _DeadlineExpired


def fetch_bytes(client: httpx.Client, url: str, seconds: float) -> bytes:
    """Download `url` whole within `seconds` (`render.pdf`, `download_pdf()`)."""
    if seconds <= 0:
        return _read_all(client, url, seconds, None)
    try:
        return _call_with_deadline(
            lambda abandoned: _read_all(client, url, seconds, abandoned), seconds
        )
    except _DeadlineExpired:
        raise _timed_out() from None


def _read_all(
    client: httpx.Client, url: str, seconds: float, abandoned: threading.Event | None
) -> bytes:
    """Read the whole body. Once `abandoned` is set (nobody waits for the bytes any more), stop
    at the next step: before the request, after the headers, or after a chunk."""

    def given_up() -> bool:
        return abandoned is not None and abandoned.is_set()

    if given_up():
        return b""
    try:
        with client.stream("GET", url, timeout=seconds) as response:
            if given_up():
                return b""  # leaving the block releases the connection
            if not response.is_success:
                raise _failed(response.status_code)
            chunks: list[bytes] = []
            for chunk in response.iter_bytes():
                if given_up():
                    break
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc


@contextmanager
def stream_bytes(
    client: httpx.Client, url: str, seconds: float
) -> Generator[Iterator[bytes], None, None]:
    """Yield the chunks of `url`, with `seconds` as an idle timeout (`render.pdf_stream`)."""
    request = client.build_request("GET", url, timeout=seconds)
    response, chunks = _open(client, request, seconds)
    try:
        if not response.is_success:
            raise _failed(response.status_code)
        yield _iter_chunks(chunks)
    finally:
        response.close()


def _open(
    client: httpx.Client, request: httpx.Request, seconds: float
) -> tuple[httpx.Response, Iterator[bytes]]:
    """Send `request` and read the first chunk of a 2xx body, all within `seconds`.

    Returns the response and an iterator over its chunks, the first one included. The
    answer's headers and the first byte share the one budget, so the first byte comes at
    most `seconds` after the request started; each later chunk has `seconds` of its own.
    """

    def start(abandoned: threading.Event) -> tuple[httpx.Response, Iterator[bytes]]:
        return _start_stream(client, request, abandoned)

    try:
        if seconds <= 0:
            return start(threading.Event())
        return _call_with_deadline(start, seconds, discard=lambda opened: opened[0].close())
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc
    except _DeadlineExpired:
        raise _timed_out() from None


def _start_stream(
    client: httpx.Client, request: httpx.Request, abandoned: threading.Event
) -> tuple[httpx.Response, Iterator[bytes]]:
    """Send `request` and read the first chunk, on the worker thread.

    Once the caller has given up (`abandoned`), stop before the request and again after the
    headers, closing the response.
    """
    if abandoned.is_set():
        raise _DeadlineExpired
    response = client.send(request, stream=True)
    try:
        if abandoned.is_set():
            raise _DeadlineExpired
        return response, _with_first_chunk(response)
    except BaseException:
        response.close()
        raise


def _with_first_chunk(response: httpx.Response) -> Iterator[bytes]:
    """Read the first chunk of a 2xx body now; return every chunk, that one first."""
    if not response.is_success:
        return iter(())
    chunks = response.iter_bytes()
    first = next(chunks, None)
    if first is None:
        return iter(())
    return itertools.chain((first,), chunks)


def _iter_chunks(chunks: Iterator[bytes]) -> Iterator[bytes]:
    try:
        yield from chunks
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc


# ---------------------------------------------------------------------------
# Async: asyncio.timeout
# ---------------------------------------------------------------------------


async def async_fetch_bytes(client: httpx.AsyncClient, url: str, seconds: float) -> bytes:
    """Download `url` whole within `seconds` (`render.pdf`, `download_pdf()`)."""
    if seconds <= 0:
        return await _async_read_all(client, url, seconds)
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            return await _async_read_all(client, url, seconds)
    except TimeoutError:
        if not deadline.expired():
            raise
        raise _timed_out() from None


async def _async_read_all(client: httpx.AsyncClient, url: str, seconds: float) -> bytes:
    try:
        async with client.stream("GET", url, timeout=seconds) as response:
            if not response.is_success:
                raise _failed(response.status_code)
            return b"".join([chunk async for chunk in response.aiter_bytes()])
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc


@asynccontextmanager
async def async_stream_bytes(
    client: httpx.AsyncClient, url: str, seconds: float
) -> AsyncGenerator[AsyncIterator[bytes], None]:
    """Yield the chunks of `url`, with `seconds` as an idle timeout (`render.pdf_stream`)."""
    request = client.build_request("GET", url, timeout=seconds)
    response, chunks = await _async_open(client, request, seconds)
    try:
        if not response.is_success:
            raise _failed(response.status_code)
        yield _aiter_chunks(chunks)
    finally:
        await response.aclose()


async def _async_open(
    client: httpx.AsyncClient, request: httpx.Request, seconds: float
) -> tuple[httpx.Response, AsyncIterator[bytes]]:
    """Send `request` and read the first chunk of a 2xx body, all within `seconds`."""

    async def start() -> tuple[httpx.Response, AsyncIterator[bytes]]:
        response = await client.send(request, stream=True)
        try:
            return response, await _async_with_first_chunk(response)
        except BaseException:
            await response.aclose()
            raise

    try:
        if seconds <= 0:
            return await start()
        deadline = asyncio.timeout(seconds)
        try:
            async with deadline:
                return await start()
        except TimeoutError:
            if not deadline.expired():
                raise
            raise _timed_out() from None
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc


async def _async_with_first_chunk(response: httpx.Response) -> AsyncIterator[bytes]:
    """Read the first chunk of a 2xx body now; return every chunk, that one first."""
    if not response.is_success:
        return _achain(None, None)
    chunks = response.aiter_bytes()
    try:
        first = await anext(chunks)
    except StopAsyncIteration:
        return _achain(None, None)
    return _achain(first, chunks)


async def _achain(first: bytes | None, rest: AsyncIterator[bytes] | None) -> AsyncIterator[bytes]:
    if first is not None:
        yield first
    if rest is not None:
        async for chunk in rest:
            yield chunk


async def _aiter_chunks(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    try:
        async for chunk in chunks:
            yield chunk
    except httpx.HTTPError as exc:
        raise _from_httpx(exc) from exc
