"""The demo's API-key handling (`demo/_shared.py`).

The demo is the first code most users run, so its key prompt follows the SDK
contract: a pasted key is checked against the contract's full-key regex and
nothing else (no list of environment names).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

CONTRACT_FULL_KEY_REGEX = (
    r"^pp_(?=[a-z][a-z0-9-]{0,19}_)[a-z][a-z0-9]*(?:-[a-z0-9]+)*_[0-9a-f]{32}$"
)
HEX32 = "0123456789abcdef" * 2


def _load_shared() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "demo" / "_shared.py"
    spec = importlib.util.spec_from_file_location("demo_shared", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shared = _load_shared()


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setattr(shared, "ENV_FILE", path)
    monkeypatch.delenv("POLI_PAGE_API_KEY", raising=False)
    monkeypatch.delenv("POLI_PAGE_BASE_URL", raising=False)
    return path


def test_key_pattern_is_the_contract_regex_verbatim() -> None:
    assert shared.API_KEY_PATTERN.pattern == CONTRACT_FULL_KEY_REGEX


@pytest.mark.parametrize(
    "key",
    [
        f"pp_sandbox_{HEX32}",
        f"pp_live_{HEX32}",
        f"pp_staging_{HEX32}",
        f"pp_staging-eu_{HEX32}",
        f"pp_a_{HEX32}",
        f"pp_{'a' * 20}_{HEX32}",
        # The format is all the demo checks: `test` is a valid environment name.
        f"pp_test_{HEX32}",
    ],
)
def test_key_pattern_accepts_well_formed_keys(key: str) -> None:
    assert shared.is_well_formed_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "pp_sandbox_x",
        f"pp_sandbox_{HEX32.upper()}",
        f"pp_sandbox_{HEX32[:-1]}",
        f"pp_sandbox_{HEX32}0",
        f"pp_staging-_{HEX32}",
        f"pp_-staging_{HEX32}",
        f"pp_staging--eu_{HEX32}",
        f"pp_1env_{HEX32}",
        f"pp_Sandbox_{HEX32}",
        f"pp_{'a' * 21}_{HEX32}",
        f"pp_sand_box_{HEX32}",
        f"PP_sandbox_{HEX32}",
        f"sk_sandbox_{HEX32}",
        f"pp_sandbox_{HEX32}\n",
        "",
    ],
)
def test_key_pattern_rejects_malformed_keys(key: str) -> None:
    assert not shared.is_well_formed_key(key)


def test_pasted_key_is_saved_when_well_formed(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = f"pp_staging-eu_{HEX32}"
    monkeypatch.setattr("builtins.input", lambda _prompt="": f"  {key}  ")

    assert shared.ensure_api_key() == key
    assert env_file.read_text(encoding="utf-8") == f"POLI_PAGE_API_KEY={key}\n"


def test_pasted_key_is_refused_when_malformed(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt="": "pp_sandbox_x")

    with pytest.raises(SystemExit) as excinfo:
        shared.ensure_api_key()

    assert excinfo.value.code == 1
    assert not env_file.exists()


def test_prompt_asks_for_a_sandbox_key(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return f"pp_sandbox_{HEX32}"

    monkeypatch.setattr("builtins.input", fake_input)

    shared.ensure_api_key()

    shown = capsys.readouterr().out + "".join(prompts)
    assert "pp_sandbox_" in shown
    assert "pp_test_" not in shown


def test_empty_api_key_env_var_counts_as_unset(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLI_PAGE_API_KEY", "")
    env_file.write_text(f"POLI_PAGE_API_KEY=pp_sandbox_{HEX32}\n", encoding="utf-8")

    assert shared.ensure_api_key() == f"pp_sandbox_{HEX32}"


def test_empty_base_url_env_var_counts_as_unset(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLI_PAGE_BASE_URL", "")

    assert shared.resolve_base_url() == "https://api.poli.page"
