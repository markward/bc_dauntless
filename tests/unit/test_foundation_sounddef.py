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


def test_sounddef_names_a_sound_the_manager_could_not_load(monkeypatch):
    """TGSoundManager.LoadSound returns None (no exception) when the backend
    refuses the load -- which is exactly what happens when the audio system
    has not been init'ed yet. That silence cost the CGSovereign mod every
    weapon sound; the boot report must name the sound instead."""
    monkeypatch.setattr(
        foundation, "_sound_manager",
        lambda: type("M", (), {"LoadSound": lambda s, p, n, l: None})())
    foundation.SoundDef("sfx/Weapons/CGQuantum.wav", "QuantumCG", 1.0)
    assert any(s.startswith("QuantumCG ") for s in foundation.sound_failures())


def test_run_brings_the_audio_backend_up_before_foundation_plugins_load():
    """SoundDef -> TGSoundManager.LoadSound -> _audio.load_sound, and the
    binding returns False until _audio.init() has run. run() used to load
    Foundation plugins ~230 lines BEFORE init_audio_backend(), so every
    Autoload SoundDef in every mod registered nothing (CGSovereign: phasers,
    quantums and photons all silent). Checked on the source, like the
    prebake-order test, so a reorder fails here and not in a live boot."""
    import ast
    import inspect
    from engine import host_loop
    tree = ast.parse(inspect.getsource(host_loop.run))
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name in ("init_audio_backend", "load_plugins"):
                order.append((node.lineno, name))
    order.sort()
    names = [n for _, n in order]
    assert "init_audio_backend" in names and "load_plugins" in names
    assert names.index("init_audio_backend") < names.index("load_plugins")
