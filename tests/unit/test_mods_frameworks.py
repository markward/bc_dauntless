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
    # FoundationTech, not Foundation: this asserts that an UNIMPLEMENTED
    # framework is reported, and we implement Foundation now. Written against
    # Foundation originally, which is how six mod lines came to claim
    # "requires: Foundation (unsupported)" while Foundation was busy
    # registering 45 of their ships.
    _touch(tmp_path / "M" / "Scripts" / "Custom" / "Ships" / "A.py",
           "import App\nimport FoundationTech\n")
    _touch(tmp_path / "M" / "Scripts" / "Ships" / "A.py", "import App\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == ["FoundationTech"]


def test_foundation_is_provided_by_the_engine(tmp_path):
    """`requires` means UNAVAILABLE, and Foundation is available: the engine
    implements it in engine/foundation/ behind the Foundation.py shim. Every
    mod in the corpus imports it -- 40 times across six packs -- so getting
    this wrong mislabels the entire report."""
    _touch(tmp_path / "M" / "Scripts" / "Custom" / "Ships" / "A.py",
           "import Foundation\n")
    idx = mods.build_index(tmp_path)
    mods.detect_frameworks(idx)
    assert {m.name: m.requires for m in idx.mods}["M"] == []


def test_the_report_does_not_call_foundation_unsupported(tmp_path):
    game = tmp_path / "stock_game"; sdk = tmp_path / "stock_sdk"
    game.mkdir(); sdk.mkdir()
    _touch(tmp_path / "mods" / "M" / "Scripts" / "Custom" / "Ships" / "A.py",
           "import Foundation\n")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    mods.detect_frameworks(idx)
    assert "Foundation" not in mods.describe(idx)


def test_an_unimplemented_framework_is_still_called_out(tmp_path):
    """The line must keep working for frameworks we genuinely lack, or
    fixing the false positive would just blind the report instead."""
    game = tmp_path / "stock_game"; sdk = tmp_path / "stock_sdk"
    game.mkdir(); sdk.mkdir()
    _touch(tmp_path / "mods" / "M" / "Scripts" / "Custom" / "A.py",
           "import FoundationTech\nimport Registry\n")
    idx = mods.build_index(tmp_path / "mods")
    mods.classify(idx, game, sdk)
    mods.detect_frameworks(idx)
    text = mods.describe(idx)
    assert "FoundationTech" in text and "Registry" in text
    assert "unsupported" in text


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


def test_comma_separated_imports_detected_through_regex_fallback():
    # Backtick-repr forces regex fallback; comma-separated imports must not be missed
    src = "import App, Foundation\nx = `1`\n"
    assert "Foundation" in mods._imported_names(src)
    assert "App" in mods._imported_names(src)


def test_comma_separated_with_submodules_detected_through_regex_fallback():
    # Multiple imports including dotted names; only root module matters
    src = "import App, Foundation.Sub\nx = `1`\n"
    names = mods._imported_names(src)
    assert "Foundation" in names
    assert "App" in names


def test_from_import_through_regex_fallback():
    # from...import through the regex fallback (not AST)
    src = "from Foundation import ShipDef\nx = `1`\n"
    assert "Foundation" in mods._imported_names(src)


def test_semicolon_separated_imports_detected_through_regex_fallback():
    # Backtick-repr forces regex fallback; semicolon-separated imports must not be missed
    src = "import App; import Foundation\nx = `1`\n"
    names = mods._imported_names(src)
    assert "Foundation" in names
    assert "App" in names
