"""PhaserBank.Fire only spawns SFX on the False→True transition of
_firing. Repeat Fire() calls while already firing must NOT create new
_PlayingSound handles for the loop sound — otherwise the AI's per-tick
StartFiring re-calls leak handles that play forever.
"""
import pytest

from engine.appc.subsystems import _EnergyWeaponFireMixin


class _FakeSnd:
    def __init__(self, name):
        self.name = name
        self.play_calls = []
        self._looping = False
    def SetLooping(self, v):
        self._looping = bool(v)
    def Play(self, attach_node=0, position=None):
        self.play_calls.append({"attach_node": attach_node, "position": position})
        class _H:
            def __init__(self):
                self.stop_calls = 0
            def Stop(self_inner):
                self_inner.stop_calls += 1
        return _H()


class _FakeMgr:
    def __init__(self):
        self.sounds = {}
    def GetSound(self, name):
        if name not in self.sounds:
            self.sounds[name] = _FakeSnd(name)
        return self.sounds[name]
    def PlaySound(self, name):
        snd = self.sounds.get(name)
        return snd.Play() if snd else None


class _FakeProperty:
    def GetFireSound(self): return "Galaxy Phaser"


class _FakeLoc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _FakeShip:
    def GetWorldLocation(self):
        return _FakeLoc(0.0, 0.0, 0.0)
    def GetNode(self):
        # Mirrors ObjectClass.GetNode(): a handle resolving GetWorldLocation.
        return self


class _FakeSystem:
    def GetParentShip(self): return _FakeShip()


class _FakeBank(_EnergyWeaponFireMixin):
    """Minimal Fire-call exerciser. CanFire always True; SFX path real."""
    def __init__(self):
        self._firing = False
        self._target = None
        self._target_offset = None
        self._loop_handle = None
        self._charge_level = 1.0
        self._min_firing_charge = 0.0
        self._parent_sys = _FakeSystem()
        self._prop = _FakeProperty()
    def CanFire(self): return 1
    def GetParentSubsystem(self): return self._parent_sys
    def GetProperty(self): return self._prop


def test_fire_spawns_loop_sfx_on_first_call(monkeypatch):
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )
    bank = _FakeBank()
    bank.Fire(target="t1")

    assert bank._firing is True
    loop = mgr.sounds["Galaxy Phaser Loop"]
    assert len(loop.play_calls) == 1
    assert bank._loop_handle is not None


def test_repeat_fire_while_already_firing_does_not_spawn_new_sfx(monkeypatch):
    """The bug: AI calls StartFiring every tick. Each call hit Fire()
    which re-spawned the loop SFX and orphaned the prior handle. Now
    Fire() while already _firing must be SFX-idempotent."""
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )
    bank = _FakeBank()

    bank.Fire(target="t1")
    handle_after_first = bank._loop_handle
    loop = mgr.sounds["Galaxy Phaser Loop"]
    assert len(loop.play_calls) == 1

    # 9 more calls within the same firing window.
    for _ in range(9):
        bank.Fire(target="t1")

    # Loop sound was only Played once across all 10 calls.
    assert len(loop.play_calls) == 1
    # _loop_handle identity preserved (no orphan).
    assert bank._loop_handle is handle_after_first


def test_fire_updates_target_even_when_already_firing(monkeypatch):
    """Re-Fire while already firing is SFX-idempotent but still
    refreshes _target / _target_offset so the bank can re-aim mid-burst."""
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )
    bank = _FakeBank()

    bank.Fire(target="t1", offset="o1")
    assert bank._target == "t1"
    bank.Fire(target="t2", offset="o2")
    assert bank._target == "t2"
    assert bank._target_offset == "o2"


def test_stopfiring_then_fire_again_spawns_new_loop(monkeypatch):
    """After StopFiring (depletion auto-stop OR external), the next
    Fire() must spawn a fresh loop SFX — the edge transition happens
    again."""
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )
    bank = _FakeBank()

    bank.Fire(target="t1")
    bank.StopFiring()
    bank.Fire(target="t1")

    loop = mgr.sounds["Galaxy Phaser Loop"]
    assert len(loop.play_calls) == 2
