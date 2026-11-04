"""`scripts/check-contract-version.sh`: a release's major.minor must be the pinned contract's.

Each test copies the script next to a `ci.yml` that pins a commit of a local contract
repository, tagged as the test needs, and points `API_CONTRACT_REMOTE` at it. Bash and git
run the script as the release does; on Windows the test is skipped (a `bash` on the PATH may
be WSL's, which cannot read the Windows paths).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-contract-version.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("git") is None,
    reason="needs bash and git on a POSIX system",
)

_GIT = [
    "git",
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
    "-c",
    "init.defaultBranch=main",
]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [*_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    )
    return done.stdout.strip()


class Contract:
    """A local contract repository and a checkout of the SDK layout that pins one commit."""

    def __init__(self, tmp_path: Path) -> None:
        self.remote = tmp_path / "api-contract"
        self.remote.mkdir()
        _git(self.remote, "init", "-q")
        self.sdk = tmp_path / "sdk"
        (self.sdk / "scripts").mkdir(parents=True)
        (self.sdk / ".github" / "workflows").mkdir(parents=True)
        shutil.copy(SCRIPT, self.sdk / "scripts" / SCRIPT.name)

    def commit(self) -> str:
        _git(self.remote, "commit", "-q", "--allow-empty", "-m", "contract")
        return _git(self.remote, "rev-parse", "HEAD")

    def tag(self, name: str, *, annotated: bool = True) -> None:
        if annotated:
            _git(self.remote, "tag", "-a", name, "-m", name)
        else:
            _git(self.remote, "tag", name)

    def pin(self, sha: str, comment: str = "# v9.9.9") -> None:
        (self.sdk / ".github" / "workflows" / "ci.yml").write_text(
            "jobs:\n  test:\n    steps:\n"
            "      - name: API contract\n"
            f"        uses: poli-page/api-contract@{sha} {comment}\n",
            encoding="utf-8",
        )

    def check(self, version: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "API_CONTRACT_REMOTE": str(self.remote)}
        return subprocess.run(
            ["bash", str(self.sdk / "scripts" / SCRIPT.name), version],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def contract(tmp_path: Path) -> Contract:
    return Contract(tmp_path)


@pytest.mark.parametrize("version", ["0.13.0", "v0.13.0", "0.13.4", "0.13.0rc1"])
def test_passes_for_the_pinned_major_minor(contract: Contract, version: str) -> None:
    sha = contract.commit()
    contract.tag("v0.13.0-dev.1")
    contract.tag("v0.13.0")
    contract.pin(sha)  # the comment says v9.9.9: only the tag on the commit counts
    result = contract.check(version)
    assert result.returncode == 0, result.stderr
    assert "API contract v0.13.0" in result.stdout


def test_reads_a_lightweight_tag(contract: Contract) -> None:
    sha = contract.commit()
    contract.tag("v0.13.0", annotated=False)
    contract.pin(sha)
    assert contract.check("0.13.0").returncode == 0


def test_fails_for_another_major_minor_and_names_both(contract: Contract) -> None:
    old = contract.commit()
    contract.tag("v0.12.0")
    contract.commit()
    contract.tag("v0.13.0")
    contract.pin(old, "# v0.13.0")  # a comment that lies
    result = contract.check("0.13.0")
    assert result.returncode == 1
    assert "release v0.13.0 and the pinned API contract v0.12.0" in result.stderr
    assert "pin the contract v0.13.x, or release v0.12.x" in result.stderr


def test_fails_when_the_pinned_commit_has_only_a_prerelease_tag(contract: Contract) -> None:
    sha = contract.commit()
    contract.tag("v0.13.0-dev.1")
    contract.pin(sha)
    result = contract.check("0.13.0")
    assert result.returncode == 1
    assert "has no stable vX.Y.Z tag" in result.stderr


def test_fails_without_a_pin(contract: Contract) -> None:
    contract.commit()
    (contract.sdk / ".github" / "workflows" / "ci.yml").write_text("jobs: {}\n", encoding="utf-8")
    result = contract.check("0.13.0")
    assert result.returncode == 1
    assert "no poli-page/api-contract pin" in result.stderr


@pytest.mark.parametrize("version", ["0.13", "latest", ""])
def test_fails_for_a_version_that_is_not_x_y_z(contract: Contract, version: str) -> None:
    sha = contract.commit()
    contract.tag("v0.13.0")
    contract.pin(sha)
    result = contract.check(version)
    assert result.returncode == 1
    assert "is not X.Y.Z" in result.stderr


def test_ignores_a_commented_out_pin(contract: Contract) -> None:
    old = contract.commit()
    contract.tag("v0.12.0")
    new = contract.commit()
    contract.tag("v0.13.0")
    contract.pin(new)
    workflow = contract.sdk / ".github" / "workflows" / "ci.yml"
    commented = f"      # uses: poli-page/api-contract@{old} # v0.12.0\n"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("      - name", commented + "      - name"),
        encoding="utf-8",
    )
    result = contract.check("0.13.0")
    assert result.returncode == 0, result.stderr


def test_fails_when_publish_pins_another_commit(contract: Contract) -> None:
    old = contract.commit()
    new = contract.commit()
    contract.tag("v0.13.0")
    contract.pin(new)
    (contract.sdk / ".github" / "workflows" / "publish.yml").write_text(
        f"      - uses: poli-page/api-contract@{old} # v0.13.0\n", encoding="utf-8"
    )
    result = contract.check("0.13.0")
    assert result.returncode == 1
    assert "pin the same commit in both" in result.stderr
    (contract.sdk / ".github" / "workflows" / "publish.yml").write_text(
        f"      - uses: poli-page/api-contract@{new} # v0.13.0\n", encoding="utf-8"
    )
    assert contract.check("0.13.0").returncode == 0
