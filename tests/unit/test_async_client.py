"""Async client (`AsyncPoliPage`) unit tests.

Parallel to test_client.py — same shape, but `await`ed and with
`asyncio.sleep` monkeypatched so retry tests stay fast.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from poli_page import (
    APIConnectionError,
    APITimeoutError,
    AsyncPoliPage,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    PoliPageError,
    RateLimitError,
    RetryEvent,
)
from poli_page._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)

TEST_BASE_URL = "https://test.example"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_s: float) -> None:
        return None

    monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _noop)


class TestConstructor:
    def test_raises_invalid_options_when_no_api_key_and_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("POLI_PAGE_API_KEY", raising=False)
        with pytest.raises(PoliPageError) as excinfo:
            AsyncPoliPage()
        assert excinfo.value.code == "invalid_options"

    def test_picks_up_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_API_KEY", "pp_test_from_env")
        client = AsyncPoliPage()
        assert isinstance(client, AsyncPoliPage)

    def test_picks_up_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_BASE_URL", "https://custom.example")
        client = AsyncPoliPage(api_key="pp_test_abc")
        assert client.base_url == "https://custom.example"

    def test_default_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLI_PAGE_BASE_URL", raising=False)
        client = AsyncPoliPage(api_key="pp_test_abc")
        assert client.base_url == DEFAULT_BASE_URL
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.retry_delay == DEFAULT_RETRY_DELAY_SECONDS
        assert client.timeout == DEFAULT_TIMEOUT_SECONDS


class TestLifecycle:
    async def test_async_context_manager_closes_owned_client(self) -> None:
        async with AsyncPoliPage(api_key="pp_test_abc") as client:
            assert isinstance(client, AsyncPoliPage)

    async def test_inject_custom_client_is_not_closed(self) -> None:
        external = httpx.AsyncClient()
        client = AsyncPoliPage(api_key="pp_test_abc", http_client=external)
        await client.aclose()
        assert not external.is_closed
        await external.aclose()


class TestPreviewHappyPath:
    @respx.mock
    async def test_posts_to_render_preview(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200,
                json={"html": "<p>x</p>", "totalPages": 1, "environment": "sandbox"},
            )
        )
        async with AsyncPoliPage(api_key="pp_test_abc", base_url=TEST_BASE_URL) as client:
            result = await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.called
        assert result.html == "<p>x</p>"
        assert result.total_pages == 1
        assert result.environment == "sandbox"

    @respx.mock
    async def test_sets_idempotency_key_and_bearer(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                200, json={"html": "", "totalPages": 1, "environment": "sandbox"}
            )
        )
        async with AsyncPoliPage(api_key="pp_test_xyz", base_url=TEST_BASE_URL) as client:
            await client.render.preview({"template": "<p>x</p>", "data": {}})
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer pp_test_xyz"
        assert len(req.headers["Idempotency-Key"]) == 36


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected_cls"),
        [
            (400, BadRequestError),
            (401, AuthenticationError),
            (403, PermissionDeniedError),
            (429, RateLimitError),
            (500, InternalServerError),
        ],
    )
    @respx.mock
    async def test_raises_classified_subclass_for_status(
        self, status: int, expected_cls: type[PoliPageError]
    ) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(
                status,
                json={"code": "SOMETHING", "message": "boom"},
                headers={"x-request-id": "req_xyz"},
            )
        )
        async with AsyncPoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(expected_cls) as excinfo:
                await client.render.preview({"template": "<p>x</p>", "data": {}})
            assert excinfo.value.status == status
            assert excinfo.value.request_id == "req_xyz"

    @respx.mock
    async def test_network_error(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            side_effect=httpx.ConnectError("refused")
        )
        async with AsyncPoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(APIConnectionError):
                await client.render.preview({"template": "<p>x</p>", "data": {}})

    @respx.mock
    async def test_timeout(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            side_effect=httpx.ReadTimeout("read timed out")
        )
        async with AsyncPoliPage(
            api_key="pp_test_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(APITimeoutError):
                await client.render.preview({"template": "<p>x</p>", "data": {}})


class TestRetryLoop:
    @respx.mock
    async def test_retries_5xx_then_succeeds(self) -> None:
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json={"html": "ok", "totalPages": 1, "environment": "sandbox"}),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        ) as client:
            result = await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert result.html == "ok"
        assert route.call_count == 3

    @respx.mock
    async def test_does_not_retry_4xx(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(400, json={"code": "bad_request"})
        )
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        ) as client:
            with pytest.raises(BadRequestError):
                await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 1

    @respx.mock
    async def test_retries_429(self) -> None:
        responses = [
            httpx.Response(429, json={"code": "rate_limited"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        ) as client:
            await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert route.call_count == 2

    @respx.mock
    async def test_retry_after_seconds_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def _track(s: float) -> None:
            sleeps.append(s)

        monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _track)
        responses = [
            httpx.Response(503, json={"code": "down"}, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
        ) as client:
            await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert sleeps == [0.0]

    @respx.mock
    async def test_retry_after_ms_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def _track(s: float) -> None:
            sleeps.append(s)

        monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _track)
        responses = [
            httpx.Response(
                503,
                json={"code": "down"},
                headers={"Retry-After": "5", "Retry-After-Ms": "250"},
            ),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
        ) as client:
            await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert sleeps == [0.25]


class TestHooks:
    @respx.mock
    async def test_on_retry_fires_before_each_retry(self) -> None:
        events: list[RetryEvent] = []
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json={"html": "", "totalPages": 1, "environment": "sandbox"}),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
            on_retry=events.append,
        ) as client:
            await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert len(events) == 2
        assert events[0].attempt == 2
        assert events[1].attempt == 3

    @respx.mock
    async def test_on_error_fires_on_terminal_failure(self) -> None:
        errors: list[PoliPageError] = []
        respx.post(f"{TEST_BASE_URL}/v1/render/preview").mock(
            return_value=httpx.Response(400, json={"code": "bad"})
        )
        async with AsyncPoliPage(
            api_key="pp_test_abc",
            base_url=TEST_BASE_URL,
            max_retries=0,
            on_error=errors.append,
        ) as client:
            with pytest.raises(BadRequestError):
                await client.render.preview({"template": "<p>x</p>", "data": {}})
        assert len(errors) == 1
        assert errors[0].status == 400
