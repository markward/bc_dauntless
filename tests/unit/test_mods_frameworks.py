from pathlib import Path

from engine import mods


def _touch(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_plain_import_is_detected():
    assert "Foundation" in mods._imported_names("import Foundation\n")


def test_from_import_is_detected():
    assert "Foundation" in mods._imported_names("from Foundation import ShipDef\n")


def test_dotted_import_records_the_root():
    assert "Foundation" in mods._imported_names("import Foundation.Sub\n")


def test_python15_syntax_falls_back_to_regex():
    # Backtick-repr is a SyntaxError under Python 3; the scan must survive it.
    src = "import Foundation\nx = `1`\n"
    assert "Foundation" in mods._imported_names(src)


def test_requires_is_recorded_per_mod(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Custom" / "Ships" / "A.py",
           "import App\nimport Foundation\n")
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "A.py", "import App\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == ["Foundation"]


def test_mod_needing_nothing_records_nothing(tmp_path):
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "A.py", "import App\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == []


def test_a_mod_providing_the_framework_itself_does_not_require_it(tmp_path):
    _touch(tmp_path / "Found" / "Scripts" / "Foundation.py", "x = 1\n")
    _touch(tmp_path / "Found" / "Scripts" / "Custom" / "A.py", "import Foundation\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["Found"] == []
