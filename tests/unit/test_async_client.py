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
    RenderInput,
    RetryEvent,
)
from poli_page._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)

TEST_BASE_URL = "https://test.example"

RENDER_INPUT: RenderInput = {"project": "billing", "template": "invoice", "data": {}}

# Wire-shape descriptor that `POST /v1/render` answers with.
RENDER_RESPONSE: dict[str, object] = {
    "documentId": "doc_render",
    "organizationId": "org_x",
    "projectId": "proj_p",
    "projectSlug": "billing",
    "templateId": "tpl_t",
    "templateSlug": "invoice",
    "environment": "sandbox",
    "apiKeyId": "key_x",
    "format": "A4",
    "orientation": "portrait",
    "locale": "en-US",
    "pageCount": 1,
    "sizeBytes": 100,
    "createdAt": "2026-01-01T00:00:00Z",
    "metadata": {},
    "presignedPdfUrl": "https://presigned.example/x.pdf",
    "expiresAt": "2026-01-01T00:15:00Z",
}


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
        monkeypatch.setenv("POLI_PAGE_API_KEY", "pp_sandbox_from_env")
        client = AsyncPoliPage()
        assert isinstance(client, AsyncPoliPage)

    def test_picks_up_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POLI_PAGE_BASE_URL", "https://custom.example")
        client = AsyncPoliPage(api_key="pp_sandbox_abc")
        assert client.base_url == "https://custom.example"

    def test_default_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POLI_PAGE_BASE_URL", raising=False)
        client = AsyncPoliPage(api_key="pp_sandbox_abc")
        assert client.base_url == DEFAULT_BASE_URL
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.retry_delay == DEFAULT_RETRY_DELAY_SECONDS
        assert client.timeout == DEFAULT_TIMEOUT_SECONDS


class TestLifecycle:
    async def test_async_context_manager_closes_owned_client(self) -> None:
        async with AsyncPoliPage(api_key="pp_sandbox_abc") as client:
            assert isinstance(client, AsyncPoliPage)

    async def test_inject_custom_client_is_not_closed(self) -> None:
        external = httpx.AsyncClient()
        client = AsyncPoliPage(api_key="pp_sandbox_abc", http_client=external)
        await client.aclose()
        assert not external.is_closed
        await external.aclose()


class TestRepr:
    """API key must never leak through repr()."""

    async def test_repr_does_not_leak_api_key(self) -> None:
        secret = "pp_sandbox_super_secret_value_do_not_leak_42"
        client = AsyncPoliPage(api_key=secret, base_url=TEST_BASE_URL)
        rendered = repr(client)
        assert secret not in rendered
        assert "super_secret" not in rendered
        await client.aclose()

    async def test_repr_shows_masked_prefix(self) -> None:
        client = AsyncPoliPage(api_key="pp_sandbox_super_secret_value", base_url=TEST_BASE_URL)
        rendered = repr(client)
        assert "AsyncPoliPage" in rendered
        assert "***" in rendered
        await client.aclose()

    async def test_repr_includes_base_url(self) -> None:
        client = AsyncPoliPage(api_key="pp_sandbox_abc", base_url="https://api.example/v9")
        rendered = repr(client)
        assert "https://api.example/v9" in rendered
        await client.aclose()


class TestWithOptions:
    """Async parity for the Anthropic-style branching factory."""

    async def test_returns_new_instance(self) -> None:
        client = AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL)
        branched = client.with_options(timeout=99.0)
        assert branched is not client
        assert isinstance(branched, AsyncPoliPage)
        await client.aclose()
        await branched.aclose()

    async def test_overrides_apply(self) -> None:
        client = AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            timeout=10.0,
            max_retries=2,
        )
        branched = client.with_options(timeout=99.0, max_retries=7)
        assert branched.timeout == 99.0
        assert branched.max_retries == 7
        await client.aclose()
        await branched.aclose()

    async def test_unspecified_options_inherited(self) -> None:
        client = AsyncPoliPage(
            api_key="pp_sandbox_inherited",
            base_url="https://api.example/v9",
            timeout=12.5,
            max_retries=4,
            retry_delay=2.5,
        )
        branched = client.with_options(timeout=99.0)
        assert branched.base_url == "https://api.example/v9"
        assert branched.max_retries == 4
        assert branched.retry_delay == 2.5
        await client.aclose()
        await branched.aclose()

    async def test_does_not_mutate_original(self) -> None:
        client = AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            timeout=10.0,
            max_retries=2,
        )
        client.with_options(timeout=99.0, max_retries=7)
        assert client.timeout == 10.0
        assert client.max_retries == 2
        await client.aclose()

    async def test_owns_its_own_http_client(self) -> None:
        client = AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL)
        branched = client.with_options(timeout=99.0)
        assert branched._http_client is not client._http_client
        await client.aclose()
        assert not branched._http_client.is_closed
        await branched.aclose()


class TestRenderHappyPath:
    @respx.mock
    async def test_posts_to_render(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(200, json=RENDER_RESPONSE)
        )
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            result = await client.render.document(RENDER_INPUT)
        assert route.called
        assert result.document_id == "doc_render"
        assert result.page_count == 1
        assert result.environment == "sandbox"

    @respx.mock
    async def test_sets_idempotency_key_and_bearer(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(200, json=RENDER_RESPONSE)
        )
        async with AsyncPoliPage(api_key="pp_sandbox_xyz", base_url=TEST_BASE_URL) as client:
            await client.render.document(RENDER_INPUT)
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer pp_sandbox_xyz"
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
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(
                status,
                json={"code": "SOMETHING", "message": "boom"},
                headers={"x-request-id": "req_xyz"},
            )
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(expected_cls) as excinfo:
                await client.render.document(RENDER_INPUT)
            assert excinfo.value.status == status
            assert excinfo.value.request_id == "req_xyz"

    @respx.mock
    async def test_network_error(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=httpx.ConnectError("refused"))
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, max_retries=0
        ) as client:
            with pytest.raises(APIConnectionError) as excinfo:
                await client.render.document(RENDER_INPUT)
        assert excinfo.value.message == "Network request failed"
        assert isinstance(excinfo.value.__cause__, httpx.ConnectError)

    @respx.mock
    async def test_timeout(self) -> None:
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            side_effect=httpx.ReadTimeout("read timed out")
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, max_retries=0, timeout=0.15
        ) as client:
            with pytest.raises(APITimeoutError) as excinfo:
                await client.render.document(RENDER_INPUT)
        assert excinfo.value.message == "Request timed out after 150ms"
        assert isinstance(excinfo.value.__cause__, httpx.ReadTimeout)


class TestRetryLoop:
    @respx.mock
    async def test_retries_5xx_then_succeeds(self) -> None:
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        ) as client:
            result = await client.render.document(RENDER_INPUT)
        assert result.document_id == "doc_render"
        assert route.call_count == 3

    @respx.mock
    async def test_does_not_retry_4xx(self) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(400, json={"code": "bad_request"})
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
        ) as client:
            with pytest.raises(BadRequestError):
                await client.render.document(RENDER_INPUT)
        assert route.call_count == 1

    @respx.mock
    async def test_retries_429(self) -> None:
        responses = [
            httpx.Response(429, json={"code": "rate_limited"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert route.call_count == 2

    @respx.mock
    async def test_retry_after_seconds_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []

        async def _track(s: float) -> None:
            sleeps.append(s)

        monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _track)
        responses = [
            httpx.Response(503, json={"code": "down"}, headers={"Retry-After": "0"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert sleeps == [0.0]

    @respx.mock
    async def test_publish_in_progress_retried_then_surfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleeps: list[float] = []

        async def _track(s: float) -> None:
            sleeps.append(s)

        monkeypatch.setattr("poli_page._async_client.asyncio.sleep", _track)
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(
                503, json={"error": "PUBLISH_IN_PROGRESS"}, headers={"Retry-After": "1"}
            )
        )
        async with AsyncPoliPage(api_key="pp_sandbox_abc", base_url=TEST_BASE_URL) as client:
            with pytest.raises(InternalServerError) as excinfo:
                await client.render.document(RENDER_INPUT)
        assert excinfo.value.code == "PUBLISH_IN_PROGRESS"
        assert route.call_count == 1 + DEFAULT_MAX_RETRIES
        assert sleeps == [1.0] * DEFAULT_MAX_RETRIES

    @respx.mock
    async def test_retry_after_ms_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
        ) as client:
            await client.render.document(RENDER_INPUT)
        # SDK spec §9.2: only Retry-After is read.
        assert sleeps == [5.0]

    @respx.mock
    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (429, "QUOTA_EXCEEDED"),
            (429, "OVERAGE_CAP_EXCEEDED"),
            (502, "STORAGE_ACCESS_DENIED"),
        ],
    )
    async def test_never_retried_codes_raise_at_once(self, status: int, code: str) -> None:
        route = respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(status, json={"error": code}, headers={"Retry-After": "1"})
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, max_retries=2
        ) as client:
            with pytest.raises(PoliPageError) as excinfo:
                await client.render.document(RENDER_INPUT)
        assert route.call_count == 1
        assert excinfo.value.code == code
        assert excinfo.value.is_retryable() is False


class TestHooks:
    @respx.mock
    async def test_on_retry_fires_before_each_retry(self) -> None:
        events: list[RetryEvent] = []
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=3,
            retry_delay=0.01,
            on_retry=events.append,
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert len(events) == 2
        assert events[0].attempt == 2
        assert events[1].attempt == 3

    @respx.mock
    async def test_on_request_fires_before_each_attempt(self) -> None:
        from poli_page import RequestEvent

        events: list[RequestEvent] = []
        responses = [
            httpx.Response(500, json={"code": "boom"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=0.01,
            on_request=events.append,
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert len(events) == 2
        assert events[0].method == "POST"
        assert events[0].attempt == 1
        assert events[1].attempt == 2

    @respx.mock
    async def test_on_response_fires_on_success(self) -> None:
        from poli_page import ResponseEvent

        events: list[ResponseEvent] = []
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(
                200,
                json=RENDER_RESPONSE,
                headers={"x-request-id": "req_async"},
            )
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc", base_url=TEST_BASE_URL, on_response=events.append
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert len(events) == 1
        assert events[0].status == 200
        assert events[0].request_id == "req_async"
        assert events[0].duration_ms >= 0.0

    @respx.mock
    async def test_on_response_not_fired_on_error_responses(self) -> None:
        from poli_page import ResponseEvent

        events: list[ResponseEvent] = []
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(500, json={"code": "boom"})
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=0,
            on_response=events.append,
        ) as client:
            with pytest.raises(InternalServerError):
                await client.render.document(RENDER_INPUT)
        assert events == []

    @respx.mock
    async def test_on_retry_event_delay_is_milliseconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[RetryEvent] = []
        responses = [
            httpx.Response(503, json={"code": "down"}, headers={"Retry-After": "1"}),
            httpx.Response(200, json=RENDER_RESPONSE),
        ]
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(side_effect=responses)
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=2,
            retry_delay=10.0,
            on_retry=events.append,
        ) as client:
            await client.render.document(RENDER_INPUT)
        assert len(events) == 1
        assert events[0].delay_ms == 1000.0

    @respx.mock
    async def test_on_error_fires_on_terminal_failure(self) -> None:
        errors: list[PoliPageError] = []
        respx.post(f"{TEST_BASE_URL}/v1/render").mock(
            return_value=httpx.Response(400, json={"code": "bad"})
        )
        async with AsyncPoliPage(
            api_key="pp_sandbox_abc",
            base_url=TEST_BASE_URL,
            max_retries=0,
            on_error=errors.append,
        ) as client:
            with pytest.raises(BadRequestError):
                await client.render.document(RENDER_INPUT)
        assert len(errors) == 1
        assert errors[0].status == 400
