import os
import stat

import pytest

from engine import mods
import engine.appc.override_routing as r
from engine.appc import mod_hardpoint_writer as mw

SRC = ('import App\n'
       'PortWarp = App.EngineProperty_Create("Port Warp")\n'
       'PortWarp.SetRadius(1.200000)\n'
       'App.g_kModelPropertyManager.RegisterLocalTemplate(PortWarp)\n')


@pytest.fixture(autouse=True)
def _clear_index():
    mods.configure(None)
    yield
    mods.configure(None)


class _Ship:
    def GetScript(self):
        return "ships.Refit"


def _mod_tree(tmp_path, body=SRC.encode()):
    f = tmp_path / "M" / "Scripts" / "ships" / "Hardpoints" / "refit.py"
    f.parent.mkdir(parents=True)
    f.write_bytes(body)
    return f


def test_mod_backed_leaf_routes_to_the_mod_file(tmp_path, monkeypatch):
    f = _mod_tree(tmp_path)
    mods.configure(mods.build_index(tmp_path))
    monkeypatch.setattr(r, "hardpoint_leaf_for_ship", lambda ship: "refit")
    t = r.resolve_override_target(_Ship())
    assert isinstance(t, r.ModHardpointFileTarget)
    assert os.path.samefile(t.path, f)
    assert t.describe().startswith("mod file: ")


def test_stock_leaf_routes_to_overrides(monkeypatch):
    monkeypatch.setattr(r, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    t = r.resolve_override_target(_Ship())
    assert isinstance(t, r.HardpointOverridesFileTarget)
    assert t.describe() == "hardpoint_overrides.py"


def test_write_edits_in_place_and_backs_up_once(tmp_path):
    f = _mod_tree(tmp_path)
    t = r.ModHardpointFileTarget(str(f))
    t.write("refit", [("Port Warp", "SetRadius", (0.5,))])
    assert "PortWarp.SetRadius(0.500000)" in f.read_text()
    orig = tmp_path / "M" / "Scripts" / "ships" / "Hardpoints" / "refit.py.orig"
    assert orig.read_bytes() == SRC.encode()
    t.write("refit", [("Port Warp", "SetRadius", (0.7,))])
    assert orig.read_bytes() == SRC.encode()          # never overwritten
    assert not (f.parent / "refit.py.tmp").exists()


def test_latin1_bytes_survive(tmp_path):
    body = ("# caf\xe9 refit\n" + SRC).encode("latin-1")
    f = _mod_tree(tmp_path, body)
    r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    out = f.read_bytes()
    assert out.startswith(b"# caf\xe9 refit\n")
    assert b"PortWarp.SetRadius(0.500000)" in out


def test_crlf_bytes_survive(tmp_path):
    f = _mod_tree(tmp_path, SRC.replace("\n", "\r\n").encode())
    r.ModHardpointFileTarget(str(f)).write("refit", [
        ("Port Warp", "__region__", 0, [("SetGlowRegionShape", (0, "Box"))])])
    out = f.read_bytes()
    assert b"\n" not in out.replace(b"\r\n", b"")


def test_failure_leaves_the_file_untouched(tmp_path, monkeypatch):
    f = _mod_tree(tmp_path)
    def boom(text, leaf, edits):
        raise ValueError("bad emit")
    monkeypatch.setattr(r._mod_writer, "rewrite", boom)
    with pytest.raises(ValueError):
        r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    assert f.read_bytes() == SRC.encode()
    assert not (f.parent / "refit.py.tmp").exists()


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX perms")
def test_unwritable_directory_raises_and_leaves_file(tmp_path):
    f = _mod_tree(tmp_path)
    (f.parent / "refit.py.orig").write_bytes(SRC.encode())   # backup already exists
    os.chmod(f.parent, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(OSError):
            r.ModHardpointFileTarget(str(f)).write("refit", [("Port Warp", "SetRadius", (0.5,))])
    finally:
        os.chmod(f.parent, stat.S_IRWXU)
    assert f.read_bytes() == SRC.encode()
