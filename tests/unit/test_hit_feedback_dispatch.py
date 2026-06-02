"""dispatch — severity routing + mutual exclusivity + player gate.

Mocks host.shield_hit, hit_vfx.spawn, audio, camera shake; asserts each
fires for the right severity and only for the right severity.
"""
import pytest

from engine.appc import hit_feedback, hit_vfx, camera_shake
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


# ── fixtures ───────────────────────────────────────────────────────────────


class _HullMarker: pass


class _Sub:
    def __init__(self, name): self.name = name
    def __repr__(self): return f"_Sub({self.name!r})"


class _Ship:
    def __init__(self, hull):
        self._hull = hull
    def GetHull(self): return self._hull


class _FakeHost:
    def __init__(self):
        self.shield_hit_calls = []
    def shield_hit(self, *, instance_id, point, rgba, intensity):
        self.shield_hit_calls.append({
            "instance_id": instance_id, "point": point,
            "rgba": rgba, "intensity": intensity,
        })


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    hit_vfx._active.clear()
    camera_shake.reset()
    hit_feedback.reset_audio_throttle()


@pytest.fixture
def spy(monkeypatch):
    """Capture audio.Play(position=) + camera_shake.apply_kick calls."""

    audio_calls = []
    kick_calls = []

    class _StubSnd:
        def Play(self, position=None):
            audio_calls.append({"position": position})
            return None

    class _StubMgr:
        def __init__(self):
            self.last_lookup = None
        def GetSound(self, name):
            self.last_lookup = name
            return _StubSnd()

    mgr = _StubMgr()
    import App
    monkeypatch.setattr(App, "g_kSoundManager", mgr, raising=False)

    # Patch GetRandomSound on both audio modules so dispatch's name
    # pick is deterministic.
    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound",
                          lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                          lambda pool: pool[0])

    def _kick(damage):
        kick_calls.append({"damage": damage})
    monkeypatch.setattr(camera_shake, "apply_kick", _kick)

    return {"audio": audio_calls, "kicks": kick_calls,
            "mgr": mgr}


# ── SHIELD ──────────────────────────────────────────────────────────────────

def test_shield_severity_fires_shield_hit_not_hit_vfx(spy):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(1.0, 2.0, 3.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=30.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert len(host.shield_hit_calls) == 1
    call = host.shield_hit_calls[0]
    assert call["instance_id"] == 42
    assert call["point"] == (1.0, 2.0, 3.0)
    # No hit_vfx descriptor pushed.
    assert hit_vfx.snapshot() == []
    # Audio: Shield Hit name picked.
    assert spy["mgr"].last_lookup == "Shield Hit"
    assert spy["audio"][0]["position"] == (1.0, 2.0, 3.0)


# ── HULL ────────────────────────────────────────────────────────────────────

def test_hull_severity_fires_hit_vfx_not_shield_hit(spy):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(0.0, 0.0, 0.0)
    normal = TGPoint3(0.0, 0.0, -1.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=normal,
        damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert host.shield_hit_calls == []
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.HULL)
    assert snap[0]["normal"].z == -1.0
    # Audio: HULL pool — first name (per stubbed GetRandomSound).
    import LoadTacticalSounds
    assert spy["mgr"].last_lookup == LoadTacticalSounds.g_lsWeaponExplosions[0]


# ── CRITICAL ───────────────────────────────────────────────────────────────

def test_critical_severity_fires_hit_vfx_critical(spy):
    hull = _HullMarker()
    sensors = _Sub("sensors")
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}
    point = TGPoint3(0.0, 0.0, 0.0)
    normal = TGPoint3(1.0, 0.0, 0.0)

    hit_feedback.dispatch(
        ship=ship, source=None, point=point, normal=normal,
        damage=80.0, subsystem=sensors,
        absorbed_shields=0.0, absorbed_subsystem=80.0, absorbed_hull=0.0,
        sub_transition="disabled",
        host=host, ship_instances=ship_instances,
    )

    assert host.shield_hit_calls == []
    snap = hit_vfx.snapshot()
    assert len(snap) == 1
    assert snap[0]["severity"] == int(Severity.CRITICAL)
    # Audio: CRITICAL pool.
    import LoadDamageHitSounds
    assert spy["mgr"].last_lookup == LoadDamageHitSounds.g_lsSubsystemCriticals[0]


# ── Player gate ────────────────────────────────────────────────────────────

def test_camera_shake_fires_when_ship_is_player(spy, monkeypatch):
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    # Make Game_GetCurrentGame().GetPlayer() return our ship.
    import App
    class _Game:
        def GetPlayer(self): return ship
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=50.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=50.0,
        sub_transition=None,
        host=host, ship_instances=ship_instances,
    )

    assert len(spy["kicks"]) == 1
    assert spy["kicks"][0]["damage"] == pytest.approx(50.0)


def test_camera_shake_does_not_fire_for_non_player_target(spy, monkeypatch):
    hull = _HullMarker()
    ship = _Ship(hull)
    other_player = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    import App
    class _Game:
        def GetPlayer(self): return other_player
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=50.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=50.0,
        sub_transition=None,
        host=host, ship_instances={ship: 42},
    )

    assert spy["kicks"] == []


# ── Headless robustness ───────────────────────────────────────────────────

def test_dispatch_with_none_host_does_not_call_shield_hit(spy):
    """host=None means no renderer; dispatch must not raise."""
    hull = _HullMarker()
    ship = _Ship(hull)
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=30.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None,
        host=None, ship_instances=None,
    )
    # No exception; SHIELD severity tried to fire shield_hit but no host
    # to call it on. hit_vfx still empty (SHIELD never spawns hit_vfx).
    assert hit_vfx.snapshot() == []


def test_dispatch_with_no_sound_manager_is_silent(spy, monkeypatch):
    """App.g_kSoundManager = None — audio path falls through silently."""
    import App
    monkeypatch.setattr(App, "g_kSoundManager", None, raising=False)

    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0,0,0), normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None,
        host=host, ship_instances={ship: 42},
    )
    # Audio silently dropped — no exception.
    # hit_vfx still pushed.
    assert len(hit_vfx.snapshot()) == 1


# ── Audio throttle ─────────────────────────────────────────────────────────

def test_audio_throttle_drops_rapid_repeats_on_same_ship(spy):
    """Two HULL hits on the same ship within 100ms produce only one
    audio play (the second is throttled). The visual + camera-shake
    paths still fire on both."""
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    kwargs = dict(
        ship=ship, source=None, point=TGPoint3(0.0, 0.0, 0.0),
        normal=None, damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None, host=host, ship_instances=ship_instances,
    )
    hit_feedback.dispatch(**kwargs)
    hit_feedback.dispatch(**kwargs)

    # Two impacts → two hit_vfx descriptors (visual fires both times).
    assert len(hit_vfx.snapshot()) == 2
    # But only one audio play.
    assert len(spy["audio"]) == 1


def test_audio_throttle_separate_ships_not_throttled(spy):
    """Two different ships taking HULL hits within 100ms BOTH play."""
    hull = _HullMarker()
    ship_a = _Ship(hull)
    ship_b = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship_a: 1, ship_b: 2}

    base = dict(
        source=None, point=TGPoint3(0.0, 0.0, 0.0), normal=None,
        damage=30.0, subsystem=hull,
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None, host=host, ship_instances=ship_instances,
    )
    hit_feedback.dispatch(ship=ship_a, **base)
    hit_feedback.dispatch(ship=ship_b, **base)

    assert len(spy["audio"]) == 2


def test_audio_throttle_separate_severities_not_throttled(spy):
    """Same ship, SHIELD then HULL in quick succession — different keys,
    both play."""
    hull = _HullMarker()
    ship = _Ship(hull)
    host = _FakeHost()
    ship_instances = {ship: 42}

    base = dict(
        ship=ship, source=None, point=TGPoint3(0.0, 0.0, 0.0),
        normal=None, damage=30.0, subsystem=hull,
        host=host, ship_instances=ship_instances,
    )
    # SHIELD hit.
    hit_feedback.dispatch(
        absorbed_shields=30.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None, **base,
    )
    # HULL hit.
    hit_feedback.dispatch(
        absorbed_shields=0.0, absorbed_subsystem=0.0, absorbed_hull=30.0,
        sub_transition=None, **base,
    )

    assert len(spy["audio"]) == 2
