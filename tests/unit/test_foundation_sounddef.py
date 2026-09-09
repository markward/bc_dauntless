"""Foundation.SoundDef -- the one Autoload call in the corpus.

The LC Intrepid Pack's Custom/Autoload/ZZ_Intrepid.py is exactly:
    Foundation.SoundDef("sfx/Weapons/ZZ_KlingonTMP2.wav", "VoyPhoton", 1.0)
"""

import pytest

from engine import foundation, mods


def _touch(p, body=b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


@pytest.fixture(autouse=True)
def _clean():
    foundation.reset()
    mods.configure(None)
    yield
    foundation.reset()
    mods.configure(None)


def test_sounddef_registers_through_the_sound_manager(monkeypatch):
    calls = []

    class _FakeMgr:
        def LoadSound(self, path, name, loadspec):
            calls.append((path, name, loadspec))
            return object()

    monkeypatch.setattr(foundation, "_sound_manager", lambda: _FakeMgr())
    foundation.SoundDef("sfx/Weapons/Zap.wav", "VoyPhoton", 1.0)

    assert calls and calls[0][1] == "VoyPhoton"
    assert calls[0][0].endswith("sfx/Weapons/Zap.wav")


def test_sounddef_resolves_a_mod_supplied_file(tmp_path, monkeypatch):
    """The whole point of Task 1: the wav lives in the MOD, not the install."""
    _touch(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav")
    mods.configure(mods.build_index(tmp_path))

    seen = []
    monkeypatch.setattr(
        foundation, "_sound_manager",
        lambda: type("M", (), {"LoadSound": lambda s, p, n, l: seen.append(p)})())
    foundation.SoundDef("sfx/Weapons/Zap.wav", "VoyPhoton", 1.0)

    assert seen and str(tmp_path / "M" / "sfx" / "Weapons" / "Zap.wav") in seen[0]


def test_sounddef_failure_is_reported_not_raised(monkeypatch):
    """A missing sound must not abort the Autoload script that declares it."""
    def _boom():
        raise RuntimeError("no audio")
    monkeypatch.setattr(foundation, "_sound_manager", _boom)
    foundation.SoundDef("sfx/nope.wav", "X", 1.0)   # must not raise
    assert any("X" in s for s in foundation.sound_failures())
