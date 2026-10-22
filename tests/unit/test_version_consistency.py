"""The version lives in one place, and the packaged build reports itself.

Two hand-maintained copies of a version number drift, and the one that drifts
is always the one nobody reads. engine/version.py is the source of truth
(engine/ is what a packaged build actually ships); pyproject.toml is a copy,
so this pins them together.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import version as ver

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _pyproject_version() -> str:
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # tomllib would do, but a regex keeps this readable and avoids caring
    # which [table] the key sits under for a two-line assertion.
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "no version key in pyproject.toml"
    return m.group(1)


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", ver.VERSION), (
        f"VERSION {ver.VERSION!r} is not MAJOR.MINOR.PATCH")


def test_pyproject_agrees_with_engine_version():
    assert _pyproject_version() == ver.VERSION, (
        "pyproject.toml and engine/version.py disagree. engine/version.py is "
        "the source of truth -- it is what a packaged build ships.")


def test_a_checkout_says_it_is_a_checkout(monkeypatch, tmp_path):
    """No marker means no recorded provenance, and the banner must say so
    rather than implying the build came from somewhere traceable."""
    monkeypatch.setattr(ver, "read_build_info", dict)
    line = ver.banner()
    assert "checkout" in line
    assert ver.VERSION in line


def test_a_packaged_build_reports_its_commit(monkeypatch):
    monkeypatch.setattr(ver, "read_build_info", lambda: {
        "version": "9.9.9", "commit": "abc1234",
        "built": "2026-10-22T00:00:00Z", "platform": "windows-x64",
    })
    line = ver.banner()
    # The marker's own version wins: it describes the bytes that shipped.
    assert "9.9.9" in line
    assert "abc1234" in line
    assert "windows-x64" in line


def test_a_corrupt_marker_does_not_stop_the_game(monkeypatch, tmp_path):
    """The identity is diagnostics. Losing it must never cost a launch."""
    from engine import paths
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    (tmp_path / paths.PACKAGED_MARKER).write_text("{not json",
                                                  encoding="utf-8")
    assert ver.read_build_info() == {}
    assert "checkout" in ver.banner()   # degrades, does not raise


def test_a_marker_that_is_not_an_object_is_ignored(monkeypatch, tmp_path):
    from engine import paths
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    (tmp_path / paths.PACKAGED_MARKER).write_text(json.dumps([1, 2]),
                                                  encoding="utf-8")
    assert ver.read_build_info() == {}
