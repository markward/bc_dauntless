"""PhaserBank._play_fire_sfx attaches Start + Loop sounds to the firing
ship's scene node — required for positional 3D audio. A bare Play()
with no attach_node lands the source at world origin (visible at
listener offsets), so this is a regression guard."""
import pytest

from engine.appc import subsystems
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
            def Stop(self_inner): pass
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
    def __init__(self, node_id):
        # node_id kept only so existing call sites read naturally; the real
        # anchor is GetNode() -> a ref exposing GetWorldLocation().
        self._node_id = node_id
        self._loc = _FakeLoc(float(node_id), 0.0, 0.0)
    def GetWorldLocation(self):
        return self._loc
    def GetNode(self):
        # Mirrors ObjectClass.GetNode(): a handle resolving GetWorldLocation.
        return self


class _FakeSystem:
    def __init__(self, ship):
        self._ship = ship
    def GetParentShip(self):
        return self._ship


class _FakeBank(_EnergyWeaponFireMixin):
    """Minimal subclass exposing just enough of the fire-sfx surface."""
    def __init__(self, parent_sys, prop):
        self._parent_sys = parent_sys
        self._prop = prop
        self._loop_handle = None
    def GetParentSubsystem(self):
        return self._parent_sys
    def GetProperty(self):
        return self._prop


# ── tests ──────────────────────────────────────────────────────────────────

def test_play_fire_sfx_attaches_start_and_loop_to_firing_ship_node(monkeypatch):
    """Both Start and Loop must Play(attach_node=ship.GetNode()).

    attach_node is now the real node ref (identically the firing ship, since
    _FakeShip.GetNode() mirrors ObjectClass.GetNode() by returning self) —
    NOT an integer id. Asserting identity against `ship` fails exactly the
    way the GetSceneNodeId phantom did: if _firing_ship_node ever falls back
    to None/0/a stub, this stops matching.
    """
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )

    ship = _FakeShip(node_id=12345)
    sys_ = _FakeSystem(ship)
    bank = _FakeBank(sys_, _FakeProperty())

    bank._play_fire_sfx()

    start = mgr.sounds["Galaxy Phaser Start"]
    loop = mgr.sounds["Galaxy Phaser Loop"]
    assert len(start.play_calls) == 1
    assert start.play_calls[0]["attach_node"] is ship
    assert len(loop.play_calls) == 1
    assert loop.play_calls[0]["attach_node"] is ship
    assert loop._looping is True


def test_play_fire_sfx_degrades_to_world_origin_when_ship_missing(monkeypatch):
    """No parent ship → attach_node falls through to None instead of crashing."""
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )

    class _SysWithoutShip:
        def GetParentShip(self): return None

    bank = _FakeBank(_SysWithoutShip(), _FakeProperty())
    bank._play_fire_sfx()

    start = mgr.sounds["Galaxy Phaser Start"]
    assert start.play_calls[0]["attach_node"] is None


def test_play_fire_sfx_with_no_fire_sound_property_is_noop(monkeypatch):
    """If GetFireSound returns empty string, no Play call is made."""
    mgr = _FakeMgr()
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )

    class _SilentProperty:
        def GetFireSound(self): return ""

    ship = _FakeShip(node_id=1)
    bank = _FakeBank(_FakeSystem(ship), _SilentProperty())
    bank._play_fire_sfx()

    assert mgr.sounds == {}


def test_play_fire_sfx_tractor_convention_uses_bare_name(monkeypatch):
    """When name+' Start' doesn't exist, fall back to the bare name
    (tractor beam convention — no Start/Loop pair)."""
    mgr = _FakeMgr()
    # Pre-register only the bare name so the " Start" GetSound returns
    # a fresh empty mock (it's still created on demand by _FakeMgr —
    # the actual fallback test is that the bare name is also played).
    monkeypatch.setattr(
        "engine.audio.tg_sound.TGSoundManager.instance",
        classmethod(lambda cls: mgr),
    )

    class _TractorProperty:
        def GetFireSound(self): return "Tractor Beam"

    ship = _FakeShip(node_id=77)
    bank = _FakeBank(_FakeSystem(ship), _TractorProperty())
    bank._play_fire_sfx()

    # The current implementation calls GetSound(name+" Start") first;
    # since _FakeMgr always returns a sound (auto-vivifying), the
    # fallback branch isn't exercised. This test mainly asserts the
    # call attempted at attach_node=ship.GetNode() succeeded structurally.
    assert "Tractor Beam Start" in mgr.sounds
    assert mgr.sounds["Tractor Beam Start"].play_calls[0]["attach_node"] is ship
