"""Pins the dynamic write guard's event coverage (tests/helpers/write_audit.py).

Every verb the guard promises is recorded with an absolute path, and reads
are not. CPython audits the DEFAULT dir_fd as -1, not None: a hook that
treats -1 as "fd-relative" silently drops every mkdir/remove/rmdir/rename,
which is why each of those has its own case here.
"""
import os
import shutil

import pytest

from engine import paths
from tests.helpers import write_audit


def _recorded(fn):
    with write_audit.recording() as records:
        fn()
    return records


def _has(records, event, path):
    return any(e == event and p == str(path) for e, p, _ in records)


def test_open_in_write_modes_is_recorded(tmp_path):
    targets = {m: tmp_path / ("f_" + m.replace("+", "plus")) for m in
               ("w", "a", "x", "r+")}
    targets["r+"].write_text("seed")

    def go():
        for mode, path in targets.items():
            with open(path, mode):
                pass
    records = _recorded(go)
    for path in targets.values():
        assert _has(records, "open", path), (path, records)


def test_os_open_with_write_flags_is_recorded(tmp_path):
    flags = [os.O_WRONLY | os.O_CREAT, os.O_RDWR | os.O_CREAT,
             os.O_WRONLY | os.O_APPEND | os.O_CREAT,
             os.O_WRONLY | os.O_TRUNC | os.O_CREAT]
    targets = [tmp_path / ("fd%d" % i) for i in range(len(flags))]

    def go():
        for path, fl in zip(targets, flags):
            os.close(os.open(path, fl))
    records = _recorded(go)
    for path in targets:
        assert _has(records, "open", path), (path, records)


def test_reads_are_not_recorded(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("x")

    def go():
        with open(f):
            pass
        with open(f, "rb"):
            pass
        os.close(os.open(f, os.O_RDONLY))
        f.read_text(encoding="utf-8")
        os.listdir(tmp_path)
    assert _recorded(go) == []


def test_default_dir_fd_verbs_are_recorded(tmp_path):
    """os.mkdir/makedirs/remove/rmdir/rename/replace, all audited with
    dir_fd=-1 (the dir_fd encoding trap)."""
    d, nested = tmp_path / "d", tmp_path / "n1" / "n2"
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_text("x")

    def go():
        os.mkdir(d)
        os.makedirs(nested)
        os.rename(a, b)
        os.replace(b, c)
        os.remove(c)
        os.rmdir(d)
    records = _recorded(go)
    for event, path in [("os.mkdir", d), ("os.mkdir", nested),
                        ("os.mkdir", nested.parent),
                        ("os.rename", a), ("os.rename", b),
                        ("os.rename", c), ("os.remove", c),
                        ("os.rmdir", d)]:
        assert _has(records, event, path), (event, path, records)


def test_shutil_verbs_record_what_they_write(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    moved = tmp_path / "moved"
    tree = tmp_path / "tree"
    src.write_text("x")
    (tree / "sub").mkdir(parents=True)

    def go():
        shutil.copyfile(src, dst)
        shutil.move(dst, moved)
        shutil.rmtree(tree)
    records = _recorded(go)
    assert _has(records, "shutil.copyfile", dst)
    assert not _has(records, "shutil.copyfile", src)  # a copy's source is read
    assert _has(records, "shutil.move", dst)
    assert _has(records, "shutil.move", moved)
    assert _has(records, "shutil.rmtree", tree)


def test_cwd_relative_write_is_resolved_against_the_cwd(tmp_path,
                                                         monkeypatch):
    monkeypatch.chdir(tmp_path)

    def go():
        with open("rel.cfg", "w"):
            pass
    records = _recorded(go)
    assert _has(records, "open", os.path.join(os.getcwd(), "rel.cfg"))


def test_records_carry_the_first_project_frame(tmp_path):
    records = _recorded(lambda: (tmp_path / "f").write_text("x"))
    assert records[0][2].startswith(__file__ + ":"), records


def test_nothing_is_recorded_outside_recording(tmp_path):
    write_audit.install_once()
    with write_audit.recording() as records:
        pass
    (tmp_path / "after").write_text("x")
    assert records == []


@pytest.fixture
def pytest_temp_elsewhere(tmp_path, monkeypatch):
    """Move the pytest-temp exemption off tmp_path, so roots built in
    tmp_path are not already exempt."""
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(tmp_path / "pt"))


def test_stray_writes_refuses_an_allowed_dir_covering_a_guarded_root(
        tmp_path, monkeypatch, pytest_temp_elsewhere):
    """A data dir at or above a guarded root would exempt every write in it,
    and the guard would pass vacuously."""
    root = tmp_path / "install"
    root.mkdir()
    rec = [("open", str(root / "Options.cfg"), "")]
    for data in (root, tmp_path):
        monkeypatch.setenv(paths.DATA_DIR_ENV, str(data))
        with pytest.raises(RuntimeError, match="vacuous"):
            write_audit.stray_writes(rec, root)


def test_stray_writes_exempts_a_separate_data_dir(tmp_path, monkeypatch,
                                                  pytest_temp_elsewhere):
    root, data = tmp_path / "install", tmp_path / "data"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(data))
    rec = [("open", str(root / "x"), ""), ("open", str(data / "y"), ""),
           ("open", str(root / "__pycache__" / "m.pyc"), "")]
    assert write_audit.stray_writes(rec, root) == [rec[0]]
