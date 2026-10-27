"""The player documents and license texts scripts/package.py ships.

package.py itself only runs on Windows, after a build, so these pin the parts
that can drift on any machine: every source exists, THIRD_PARTY_NOTICES names
exactly the license files that ship, and an unfilled placeholder is caught.
"""
import importlib.util
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOTICES = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "dauntless_package_script", PROJECT_ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load_package()


def test_every_player_document_source_exists():
    for name, src in package.DIST_DOCS.items():
        assert src.is_file(), f"{name}: missing source {src}"


def test_shipped_documents_are_plain_text_names():
    # A double-click must open them; .md has no default handler on Windows.
    assert all(name.endswith(".txt") for name in package.DIST_DOCS)


def test_license_sources_in_the_repo_exist():
    # build/_deps entries exist only after a CMake configure, so they are
    # checked at staging time instead; everything vendored is checked here.
    for name, src in package.third_party_licenses().items():
        if package.BUILD in src.parents:
            continue
        assert src.is_file(), f"{name}: missing source {src}"


def test_python_license_resolves():
    assert package.python_license().is_file()


def test_notices_name_exactly_the_licenses_that_ship():
    named = set(re.findall(r"`%s/([^`]+)`" % package.LICENSES_DIR,
                           NOTICES.read_text(encoding="utf-8")))
    assert named == set(package.third_party_licenses())


def test_unfinished_docs_reports_a_placeholder(tmp_path, monkeypatch):
    done = tmp_path / "done.txt"
    done.write_text("all filled in\n", encoding="utf-8")
    draft = tmp_path / "draft.txt"
    draft.write_text("Download: %s link]]\n" % package.DOC_PLACEHOLDER,
                     encoding="utf-8")
    monkeypatch.setattr(package, "DIST_DOCS",
                        {"DONE.txt": done, "DRAFT.txt": draft})
    assert package.unfinished_docs() == ["DRAFT.txt"]


def test_stage_docs_copies_documents_and_licenses(tmp_path, monkeypatch):
    sources = {}
    for name in ("A-LICENSE.txt", "B-CREDITS.html"):
        src = tmp_path / "src" / name
        src.parent.mkdir(exist_ok=True)
        src.write_text(name, encoding="utf-8")
        sources[name] = src
    monkeypatch.setattr(package, "third_party_licenses", lambda: sources)
    app = tmp_path / "app"
    app.mkdir()

    package.stage_docs(app)

    for name in package.DIST_DOCS:
        assert (app / name).read_bytes() == package.DIST_DOCS[name].read_bytes()
    for name in sources:
        assert (app / package.LICENSES_DIR / name).read_text(
            encoding="utf-8") == name


def test_stage_docs_refuses_a_missing_license(tmp_path, monkeypatch):
    monkeypatch.setattr(package, "third_party_licenses",
                        lambda: {"Gone-LICENSE.txt": tmp_path / "nope"})
    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(SystemExit, match="missing license text"):
        package.stage_docs(app)
