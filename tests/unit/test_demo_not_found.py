"""The demos' last step (`not-found`) checks the API's missing-template contract.

Each demo runs end to end against a mocked API. Step 9 passes only on
`404 TEMPLATE_NOT_FOUND`: any other error, or a render that succeeds, ends the
demo with a non-zero exit and without "All steps completed".
"""

from __future__ import annotations

import json
import runpy
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
import respx

BASE_URL = "https://test.example"
PRESIGNED_URL = "https://presigned.example/demo.pdf"
DOCUMENT_ID = "doc_demo"
DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
DEMOS = ["sync_demo.py", "async_demo.py"]

DESCRIPTOR: dict[str, object] = {
    "documentId": DOCUMENT_ID,
    "organizationId": "org_x",
    "projectId": "proj_p",
    "projectSlug": "getting-started",
    "templateId": "tpl_t",
    "templateSlug": "welcome",
    "environment": "sandbox",
    "apiKeyId": "key_x",
    "format": "A4",
    "orientation": "portrait",
    "locale": "en-US",
    "pageCount": 1,
    "sizeBytes": 26,
    "createdAt": "2026-01-01T00:00:00Z",
    "metadata": {},
    "presignedPdfUrl": PRESIGNED_URL,
    "expiresAt": "2026-01-01T00:15:00Z",
}


def _run_demo(
    script: str,
    not_found_answer: tuple[int, Mapping[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A copy of the demo folder, so the demo writes its output under tmp_path.
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    for name in ["_shared.py", *DEMOS]:
        shutil.copy(DEMO_DIR / name, demo_dir / name)
    monkeypatch.syspath_prepend(str(demo_dir))
    monkeypatch.delitem(sys.modules, "_shared", raising=False)
    monkeypatch.setenv("POLI_PAGE_API_KEY", f"pp_sandbox_{'0123456789abcdef' * 2}")
    monkeypatch.setenv("POLI_PAGE_BASE_URL", BASE_URL)

    def render(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["template"] == "does-not-exist":
            status, body = not_found_answer
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=DESCRIPTOR)

    documents = f"{BASE_URL}/v1/documents/{DOCUMENT_ID}"
    with respx.mock(assert_all_called=False) as api:
        api.post(f"{BASE_URL}/v1/render").mock(side_effect=render)
        api.get(PRESIGNED_URL).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 demo"))
        api.get(documents).mock(return_value=httpx.Response(200, json=DESCRIPTOR))
        api.post(f"{documents}/thumbnails").mock(
            return_value=httpx.Response(403, json={"code": "THUMBNAILS_NOT_AVAILABLE"})
        )
        api.get(f"{documents}/preview").mock(
            return_value=httpx.Response(
                200, text="<html></html>", headers={"X-Document-Page-Count": "1"}
            )
        )
        api.delete(documents).mock(return_value=httpx.Response(204))
        runpy.run_path(str(demo_dir / script), run_name="__main__")


@pytest.mark.parametrize("script", DEMOS)
def test_demo_completes_on_template_not_found(
    script: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answer = (404, {"code": "TEMPLATE_NOT_FOUND", "message": "no template"})

    _run_demo(script, answer, tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "code='TEMPLATE_NOT_FOUND'  status=404" in out
    assert "All steps completed." in out


@pytest.mark.parametrize("script", DEMOS)
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param((404, {"code": "PROJECT_NOT_FOUND"}), id="other-code"),
        pytest.param((400, {"code": "TEMPLATE_NOT_FOUND"}), id="other-status"),
        pytest.param((200, DESCRIPTOR), id="render-succeeds"),
    ],
)
def test_demo_fails_unless_template_not_found(
    script: str,
    answer: tuple[int, Mapping[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run_demo(script, answer, tmp_path, monkeypatch)

    assert excinfo.value.code not in (0, None)
    assert "All steps completed." not in capsys.readouterr().out
