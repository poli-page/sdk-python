"""A 2xx answer whose body is not JSON, from a method that expects JSON: `invalid_response`.

The API hop of the three render methods, `documents.get` and `documents.thumbnails` expect
JSON. Such a body comes from something between the SDK and the API (a proxy, a captive
portal), so the error keeps the real status and the `x-request-id`, is never retried, and
`on_error` sees it. `documents.preview` (HTML) and `documents.delete` expect no JSON.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
import respx

from poli_page import AsyncPoliPage, InvalidResponseError, PoliPage, PoliPageError

BASE = "https://test.example"
INPUT: dict[str, Any] = {"project": "p", "template": "t", "data": {}}
HTML = "<html><body><h1>Welcome</h1></body></html>"


def _not_json(status: int = 200, text: str = HTML) -> httpx.Response:
    return httpx.Response(
        status, text=text, headers={"content-type": "text/html", "x-request-id": "req_proxy"}
    )


SyncCall = Callable[[PoliPage], object]
AsyncCall = Callable[[AsyncPoliPage], Awaitable[object]]


async def _async_pdf_stream(client: AsyncPoliPage) -> object:
    async with client.render.pdf_stream(INPUT) as chunks:  # type: ignore[arg-type]
        return [chunk async for chunk in chunks]


def _sync_pdf_stream(client: PoliPage) -> object:
    with client.render.pdf_stream(INPUT) as chunks:  # type: ignore[arg-type]
        return list(chunks)


# (name, HTTP method, path, sync call, async call)
JSON_METHODS: list[tuple[str, str, str, SyncCall, AsyncCall]] = [
    (
        "render.document",
        "POST",
        "/v1/render",
        lambda c: c.render.document(INPUT),  # type: ignore[arg-type]
        lambda c: c.render.document(INPUT),  # type: ignore[arg-type]
    ),
    (
        "render.pdf",
        "POST",
        "/v1/render",
        lambda c: c.render.pdf(INPUT),  # type: ignore[arg-type]
        lambda c: c.render.pdf(INPUT),  # type: ignore[arg-type]
    ),
    ("render.pdf_stream", "POST", "/v1/render", _sync_pdf_stream, _async_pdf_stream),
    (
        "documents.get",
        "GET",
        "/v1/documents/doc_1",
        lambda c: c.documents.get("doc_1"),
        lambda c: c.documents.get("doc_1"),
    ),
    (
        "documents.thumbnails",
        "POST",
        "/v1/documents/doc_1/thumbnails",
        lambda c: c.documents.thumbnails("doc_1"),
        lambda c: c.documents.thumbnails("doc_1"),
    ),
]
IDS = [m[0] for m in JSON_METHODS]


def _assert_invalid_response(err: PoliPageError, status: int = 200) -> None:
    assert isinstance(err, InvalidResponseError)
    assert err.code == "invalid_response"
    assert err.message == f"Invalid response: HTTP {status} body is not JSON"
    assert err.status == status
    assert err.request_id == "req_proxy"
    assert err.is_retryable() is False
    assert err.is_network_error() is False
    assert isinstance(err.__cause__, json.JSONDecodeError)
    assert err.to_payload()["status"] == 502


class TestSync:
    @pytest.mark.parametrize(("name", "verb", "path", "call", "_a"), JSON_METHODS, ids=IDS)
    @respx.mock
    def test_raises_once_without_retry(
        self, name: str, verb: str, path: str, call: SyncCall, _a: AsyncCall
    ) -> None:
        route = respx.route(method=verb, url=f"{BASE}{path}").mock(return_value=_not_json())
        errors: list[PoliPageError] = []
        client = PoliPage(api_key="pp_sandbox_x", base_url=BASE, on_error=errors.append)
        with pytest.raises(PoliPageError) as excinfo:
            call(client)
        _assert_invalid_response(excinfo.value)
        assert route.call_count == 1
        assert errors == [excinfo.value]

    @pytest.mark.parametrize("status", [201, 204])
    @respx.mock
    def test_keeps_the_real_2xx(self, status: int) -> None:
        respx.get(f"{BASE}/v1/documents/doc_1").mock(return_value=_not_json(status, ""))
        client = PoliPage(api_key="pp_sandbox_x", base_url=BASE)
        with pytest.raises(PoliPageError) as excinfo:
            client.documents.get("doc_1")
        _assert_invalid_response(excinfo.value, status)

    @respx.mock
    def test_preview_expects_html(self) -> None:
        respx.get(f"{BASE}/v1/documents/doc_1/preview").mock(return_value=_not_json())
        client = PoliPage(api_key="pp_sandbox_x", base_url=BASE)
        assert client.documents.preview("doc_1").html == HTML

    @respx.mock
    def test_delete_ignores_the_body(self) -> None:
        respx.delete(f"{BASE}/v1/documents/doc_1").mock(return_value=_not_json())
        client = PoliPage(api_key="pp_sandbox_x", base_url=BASE)
        result = client.documents.delete("doc_1")
        assert result is None

    @respx.mock
    def test_an_error_answer_that_is_not_json_is_still_internal_error(self) -> None:
        respx.get(f"{BASE}/v1/documents/doc_1").mock(return_value=_not_json(404))
        client = PoliPage(api_key="pp_sandbox_x", base_url=BASE, max_retries=0)
        with pytest.raises(PoliPageError) as excinfo:
            client.documents.get("doc_1")
        assert excinfo.value.code == "INTERNAL_ERROR"
        assert excinfo.value.message == "HTTP 404"


class TestAsync:
    @pytest.mark.parametrize(("name", "verb", "path", "_s", "call"), JSON_METHODS, ids=IDS)
    @respx.mock
    async def test_raises_once_without_retry(
        self, name: str, verb: str, path: str, _s: SyncCall, call: AsyncCall
    ) -> None:
        route = respx.route(method=verb, url=f"{BASE}{path}").mock(return_value=_not_json())
        errors: list[PoliPageError] = []
        async with AsyncPoliPage(
            api_key="pp_sandbox_x", base_url=BASE, on_error=errors.append
        ) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await call(client)
        _assert_invalid_response(excinfo.value)
        assert route.call_count == 1
        assert errors == [excinfo.value]

    @respx.mock
    async def test_preview_and_delete_expect_no_json(self) -> None:
        respx.get(f"{BASE}/v1/documents/doc_1/preview").mock(return_value=_not_json())
        respx.delete(f"{BASE}/v1/documents/doc_1").mock(return_value=_not_json())
        async with AsyncPoliPage(api_key="pp_sandbox_x", base_url=BASE) as client:
            preview = await client.documents.preview("doc_1")
            deleted = await client.documents.delete("doc_1")
        assert preview.html == HTML
        assert deleted is None
