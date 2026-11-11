"""engine.stock_scripts boot install check (spec 2026-11-11-no-sdk-runtime
§4.1a, decision 7): every manifest file is hashed at boot; a missing or
unliftable listed file stops boot naming it; an unknown hash is lifted once
to prove it lifts, and a positive verdict is cached by hash.

Fake trees with an injected manifest; real retail bytes only where a real
lift is needed.
"""
import ast
import dataclasses
import hashlib
import json
import re

import pytest

from engine import paths, py15, stock_scripts
from engine.core import case_paths
from tests.helpers import write_audit
from tests.helpers.bc_assets import require_game_dir

E1M1 = "Maelstrom/Episode1/E1M1/E1M1.pyc"
H = "0" * 32
VERDICTS = "stock_lift_verdicts.json"


def _hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _put(root, rel, data=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _install(tmp_path, files=None, markers=True):
    """A fake game root: the marker folders, then scripts/<rel> per file."""
    root = tmp_path / "bc"
    root.mkdir(exist_ok=True)
    if markers:
        for m in paths.GAME_MARKERS:
            (root / m).mkdir(parents=True, exist_ok=True)
    for rel, data in (files or {}).items():
        _put(root / "scripts", rel, data)
    return root


def _retail_bytes(rel=E1M1):
    scripts = require_game_dir("scripts")
    found = case_paths.resolve(scripts, rel)
    if found is None:
        pytest.skip(f"BC assets not available: scripts/{rel}")
    return found.read_bytes()


def _no_lift(*_a, **_k):
    raise AssertionError("a known-hash file must not be lifted")


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(paths, "cache_dir", lambda: cache)
    yield
    stock_scripts.configure(None, None)


def _verdicts(tmp_path):
    return json.loads((tmp_path / "cache" / VERDICTS).read_text("utf-8"))


def test_clean_install_is_ok_and_lifts_nothing(tmp_path, monkeypatch):
    root = _install(tmp_path, {"A.pyc": b"a", "AI/Preprocessors.pyc": b"b"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")],
                             "AI/Preprocessors.pyc": [H, _hash(b"b")]}, None)
    monkeypatch.setattr(py15, "lift_file", _no_lift)
    monkeypatch.setattr(py15, "lift", _no_lift)
    check = stock_scripts.check_install(root)
    assert check == stock_scripts.InstallCheck(
        ok=True, missing=(), unliftable=(), changed=(), message="")
    assert not (tmp_path / "cache" / VERDICTS).exists()


def test_missing_listed_file_fails_naming_it(tmp_path):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")],
                             "AI/Preprocessors.pyc": [H]}, None)
    check = stock_scripts.check_install(root)
    assert not check.ok
    assert check.missing == ("scripts/AI/Preprocessors.pyc",)
    assert check.unliftable == () and check.changed == ()
    assert check.message == (
        "Your Bridge Commander scripts folder is incomplete: "
        "scripts/AI/Preprocessors.pyc is missing. Reinstall Bridge Commander "
        "or pick another install.")


def test_listed_folder_in_place_of_a_file_counts_as_missing(tmp_path):
    root = _install(tmp_path)
    (root / "scripts" / "Gone.pyc").mkdir(parents=True)
    stock_scripts.configure({"Gone.pyc": [H]}, None)
    check = stock_scripts.check_install(root)
    assert check.missing == ("scripts/Gone.pyc",)


def test_unliftable_unknown_file_fails_naming_it(tmp_path, capsys):
    root = _install(tmp_path, {"Broken.pyc": b"not bytecode at all"})
    stock_scripts.configure({"Broken.pyc": ["f" * 32]}, None)
    check = stock_scripts.check_install(root)
    assert not check.ok
    assert check.unliftable == ("scripts/Broken.pyc",)
    assert check.changed == ("scripts/Broken.pyc",)
    assert check.missing == ()
    assert check.message.startswith(
        "BC Dauntless can't read scripts/Broken.pyc in this Bridge Commander "
        "install (")
    assert "not a readable Python 1.5 .pyc" in check.message
    assert check.message.endswith(
        "). It may be modded: please use a clean install.")
    # A failed lift is never cached.
    assert not (tmp_path / "cache" / VERDICTS).exists()
    assert "[stock-scripts] scripts/Broken.pyc differs" in capsys.readouterr().out


def test_lifted_but_uncompilable_file_is_unliftable(tmp_path, monkeypatch):
    root = _install(tmp_path, {"Odd.pyc": b"odd"})
    stock_scripts.configure({"Odd.pyc": ["f" * 32]}, None)
    bad = ast.Module(body=[ast.Expr(ast.Name(id="x", ctx=ast.Store()))],
                     type_ignores=[])
    monkeypatch.setattr(py15, "lift_file", lambda _p: ast.fix_missing_locations(bad))
    check = stock_scripts.check_install(root)
    assert check.unliftable == ("scripts/Odd.pyc",)
    assert "does not compile" in check.message
    assert not (tmp_path / "cache" / VERDICTS).exists()


def test_unknown_but_liftable_file_is_ok_and_recorded_as_changed(tmp_path, capsys):
    data = _retail_bytes()
    root = _install(tmp_path, {E1M1: data})
    stock_scripts.configure({E1M1: ["f" * 32]}, None)
    check = stock_scripts.check_install(root)
    assert check.ok and check.message == ""
    assert check.changed == ("scripts/" + E1M1,)
    assert check.missing == () and check.unliftable == ()
    line = ("[stock-scripts] scripts/%s differs from every known retail copy "
            "(the install may be modded); loading it anyway" % E1M1)
    # The check and a later import share ONE warning per file per process.
    stock_scripts.configure({E1M1: ["f" * 32]}, root / "scripts")
    sf = stock_scripts.find("Maelstrom/Episode1/E1M1/E1M1")
    stock_scripts.load_tree(str(sf.path), "Maelstrom.Episode1.E1M1.E1M1")
    assert capsys.readouterr().out.count(line) == 1


def test_verdict_cache_skips_the_second_lift(tmp_path, monkeypatch):
    data = _retail_bytes()
    root = _install(tmp_path, {E1M1: data})
    stock_scripts.configure({E1M1: ["f" * 32]}, None)
    assert stock_scripts.check_install(root).ok

    saved = _verdicts(tmp_path)
    assert set(saved) == {"format", "lifts"}
    assert saved["format"] == 1
    assert saved["lifts"] == [_hash(data)]
    assert all(re.fullmatch(r"[0-9a-f]{32}", h) for h in saved["lifts"])

    lifts = []
    real = py15.lift_file
    monkeypatch.setattr(py15, "lift_file",
                        lambda p: lifts.append(p) or real(p))
    again = stock_scripts.check_install(root)
    assert again.ok and again.changed == ("scripts/" + E1M1,)
    assert lifts == []


def test_malformed_verdict_cache_is_ignored(tmp_path, monkeypatch):
    root = _install(tmp_path, {"New.pyc": b"new"})
    stock_scripts.configure({"New.pyc": ["f" * 32]}, None)
    _put(tmp_path / "cache", VERDICTS,
         json.dumps({"format": 1, "lifts": [_hash(b"new").upper(), 7]}).encode())
    lifts = []
    monkeypatch.setattr(py15, "lift_file",
                        lambda p: lifts.append(p) or ast.Module(body=[], type_ignores=[]))
    assert stock_scripts.check_install(root).ok
    assert len(lifts) == 1
    assert _verdicts(tmp_path) == {"format": 1, "lifts": [_hash(b"new")]}


def test_verdict_cache_write_failure_is_reported_not_raised(tmp_path, monkeypatch):
    root = _install(tmp_path, {"New.pyc": b"new"})
    stock_scripts.configure({"New.pyc": ["f" * 32]}, None)
    blocker = _put(tmp_path, "not_a_dir")
    monkeypatch.setattr(paths, "cache_dir", lambda: blocker / "cache")
    monkeypatch.setattr(py15, "lift_file",
                        lambda _p: ast.Module(body=[], type_ignores=[]))
    reported = []
    monkeypatch.setattr(paths, "report_write_failure",
                        lambda path, exc: reported.append(str(path)))
    assert stock_scripts.check_install(root).ok
    assert reported == [str(blocker / "cache" / VERDICTS)]


def test_check_writes_only_the_verdict_cache(tmp_path):
    data = _retail_bytes()
    root = _install(tmp_path, {E1M1: data})
    stock_scripts.configure({E1M1: ["f" * 32]}, None)
    write_audit.install_once()
    with write_audit.recording() as records:
        stock_scripts.check_install(root)
    assert records
    assert write_audit.under(records, tmp_path / "cache") == records, records


def test_validate_install_reports_markers_before_scripts(tmp_path, monkeypatch):
    root = _install(tmp_path, {"A.pyc": b"a"}, markers=False)
    stock_scripts.configure({"A.pyc": [H]}, None)

    def _never(_root):
        raise AssertionError("scripts are checked only once markers pass")
    monkeypatch.setattr(stock_scripts, "check_install", _never)
    v = stock_scripts.validate_install(root)
    assert not v.ok
    assert v == paths.validate_game_root(root)
    assert "data" in v.missing


def test_validate_install_fails_naming_the_file(tmp_path):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")], "Gone.pyc": [H]}, None)
    v = stock_scripts.validate_install(root)
    assert not v.ok
    assert v.root == paths.normalise(root)
    assert v.missing == ("scripts/Gone.pyc",)
    assert v.hint == stock_scripts.check_install(root).message


def test_validate_install_passes_a_good_install(tmp_path):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")]}, None)
    assert stock_scripts.validate_install(root) == paths.validate_game_root(root)


def _resolution(game, validation):
    values = {f.name: None for f in dataclasses.fields(paths.Resolution)}
    values.update({name: "" for name in values if name.endswith("_source")})
    values.update(game=game, game_source="cli", game_validation=validation)
    return paths.Resolution(**values)


def test_checked_turns_a_bad_install_into_an_unresolved_game(tmp_path):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")], "Gone.pyc": [H]}, None)
    res = _resolution(paths.normalise(root), paths.validate_game_root(root))
    out = stock_scripts.checked(res)
    assert out.game is None
    assert out.game_source == "cli"
    assert not out.game_validation.ok
    assert "scripts/Gone.pyc" in out.game_validation.hint


def test_checked_keeps_a_good_or_unresolved_game(tmp_path):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")]}, None)
    good = _resolution(paths.normalise(root), paths.validate_game_root(root))
    assert stock_scripts.checked(good) is good
    unresolved = _resolution(None, paths.validate_game_root(tmp_path / "nope"))
    assert stock_scripts.checked(unresolved) is unresolved


def test_require_install_raises_with_the_message_and_is_memoised(tmp_path, monkeypatch):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")], "Gone.pyc": [H]}, None)
    hashed = []
    real = stock_scripts._digest
    monkeypatch.setattr(stock_scripts, "_digest",
                        lambda data: hashed.append(1) or real(data))
    with pytest.raises(stock_scripts.StockInstallError) as first:
        stock_scripts.require_install(root)
    assert isinstance(first.value, RuntimeError)
    assert str(first.value) == stock_scripts.check_install(root).message
    assert "scripts/Gone.pyc" in str(first.value)
    hashed.clear()
    with pytest.raises(stock_scripts.StockInstallError) as second:
        stock_scripts.require_install(root)
    assert str(second.value) == str(first.value)
    assert hashed == []


def test_require_install_returns_a_good_check_once(tmp_path, monkeypatch):
    root = _install(tmp_path, {"A.pyc": b"a"})
    stock_scripts.configure({"A.pyc": [_hash(b"a")]}, None)
    hashed = []
    real = stock_scripts._digest
    monkeypatch.setattr(stock_scripts, "_digest",
                        lambda data: hashed.append(1) or real(data))
    assert stock_scripts.require_install(root).ok
    assert stock_scripts.require_install(root).ok
    assert len(hashed) == 1


def test_message_names_at_most_three_files(tmp_path):
    names = ["A.pyc", "B.pyc", "C.pyc", "D.pyc", "E.pyc"]
    root = _install(tmp_path)
    stock_scripts.configure({n: [H] for n in names}, None)
    check = stock_scripts.check_install(root)
    assert check.missing == tuple("scripts/" + n for n in names)
    assert check.message == (
        "Your Bridge Commander scripts folder is incomplete: scripts/A.pyc, "
        "scripts/B.pyc, scripts/C.pyc and 2 more are missing. Reinstall "
        "Bridge Commander or pick another install.")


def test_message_names_two_missing_and_several_unliftable(tmp_path):
    bad = {n: b"junk" for n in ("P.pyc", "Q.pyc", "R.pyc", "S.pyc")}
    root = _install(tmp_path, bad)
    manifest = {n: ["f" * 32] for n in bad}
    manifest.update({"X.pyc": [H], "Y.pyc": [H]})
    stock_scripts.configure(manifest, None)
    check = stock_scripts.check_install(root)
    missing, unliftable = check.message.split(" BC Dauntless", 1)
    assert missing == (
        "Your Bridge Commander scripts folder is incomplete: scripts/X.pyc "
        "and scripts/Y.pyc are missing. Reinstall Bridge Commander or pick "
        "another install.")
    assert unliftable.startswith(
        " can't read scripts/P.pyc, scripts/Q.pyc, scripts/R.pyc and 1 more "
        "in this Bridge Commander install (scripts/P.pyc: ")
    assert unliftable.endswith("). It may be modded: please use a clean install.")
