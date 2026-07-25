import pytest

import engine.appc.override_routing as r
from engine.appc import hardpoint_override_writer as w


class _StatsMod:
    @staticmethod
    def GetShipStats():
        return {"HardpointFile": "galaxy"}


class _Ship:
    def __init__(self, script):
        self._s = script

    def GetScript(self):
        return self._s


def test_leaf_for_ship_reads_hardpointfile(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module", lambda name: _StatsMod)
    assert r.hardpoint_leaf_for_ship(_Ship("ships.Galaxy")) == "galaxy"


def test_leaf_for_ship_none_safe():
    assert r.hardpoint_leaf_for_ship(_Ship("")) is None
    assert r.hardpoint_leaf_for_ship(object()) is None


def test_file_target_persists_radius_edit(tmp_path):
    f = tmp_path / "hardpoint_overrides.py"
    f.write_text(w.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}}))
    target = r.HardpointOverridesFileTarget(str(f))
    target.write("galaxy", [("Center Impulse", "SetRadius", (0.5,))])
    # Re-read the file and confirm the value changed (and only once).
    import types
    m = types.ModuleType("x"); exec(f.read_text(), m.__dict__)  # noqa: S102
    models = w.read_models(m)
    assert models["galaxy"]["Center Impulse"] == [("SetRadius", (0.5,))]


def test_resolve_returns_file_target(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module", lambda name: _StatsMod)
    assert isinstance(r.resolve_override_target(_Ship("ships.Galaxy")),
                      r.HardpointOverridesFileTarget)


def test_write_aborts_without_touching_file_on_bad_emit(tmp_path, monkeypatch):
    f = tmp_path / "hardpoint_overrides.py"
    original = w.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}})
    f.write_text(original)
    target = r.HardpointOverridesFileTarget(str(f))

    def _bad_emit(models):
        raise ValueError("bad emit")

    monkeypatch.setattr(r._writer, "emit", _bad_emit)

    with pytest.raises(ValueError):
        target.write("galaxy", [("Center Impulse", "SetRadius", (0.5,))])

    assert f.read_text() == original
    assert not (tmp_path / "hardpoint_overrides.py.tmp").exists()
