"""Pure logic of the stock manifest generator (fake trees, no BC content)."""
import hashlib

from tools import gen_stock_manifest as g


def _h(data):
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def test_build_lists_every_pyc_with_its_hash(tmp_path):
    scripts = tmp_path / "scripts"
    (scripts / "AI").mkdir(parents=True)
    (scripts / "AI" / "Pre.pyc").write_bytes(b"one")
    (scripts / "Top.pyc").write_bytes(b"two")
    out = g.build(scripts, tmp_path / "root")
    assert out == {"AI/Pre.pyc": [_h(b"one")], "Top.pyc": [_h(b"two")]}


def test_build_ignores_py_and_other_files(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "A.pyc").write_bytes(b"a")
    (scripts / "B.py").write_text("x")
    (scripts / "C.txt").write_text("x")
    assert list(g.build(scripts, tmp_path / "root")) == ["A.pyc"]


def test_project_root_shims_are_excluded(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "App.py").write_text("x")
    (scripts / "App.pyc").write_bytes(b"a")
    (scripts / "Other.pyc").write_bytes(b"b")
    assert list(g.build(scripts, root)) == ["Other.pyc"]


def test_merge_appends_hashes_never_replaces():
    merged = g.merge({"A.pyc": ["h1"]}, {"A.pyc": ["h2"], "B.pyc": ["h3"]})
    assert merged == {"A.pyc": ["h1", "h2"], "B.pyc": ["h3"]}


def test_serialise_is_deterministic():
    a = g.serialise({"A.pyc": ["x"], "B.pyc": ["y"]})
    b = g.serialise({"B.pyc": ["y"], "A.pyc": ["x"]})
    assert a == b and a.endswith("\n")
