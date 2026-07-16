import gc
import os
import struct
import weakref
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import engine_rumble, hum_allocator
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _Loc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _Prop:
    def GetEngineSound(self): return "Federation Engines"


class _Sub:
    def GetProperty(self): return _Prop()


class _Ship:
    def __init__(self, name, x):
        self._name, self._loc = name, _Loc(float(x), 0.0, 0.0)
    def GetName(self): return self._name
    def GetImpulseEngineSubsystem(self): return _Sub()
    def GetWorldLocation(self): return self._loc
    def GetNode(self): return self


class _NoEngine(_Ship):
    def GetImpulseEngineSubsystem(self): return None


class _WeakNodeRef:
    """Mirrors ObjectClass._ObjectNodeRef: a WEAK handle back to the owner,
    same as every real ship's GetNode() returns. `_Ship.GetNode` above
    returns `self` directly for simplicity in the other tests in this file,
    which would give attached_sources._attached a spurious STRONG reference
    and mask the exact leak test_ship_gc_without_teardown_stops_its_hum
    exists to catch."""
    def __init__(self, owner):
        self._owner = weakref.ref(owner)

    def GetWorldLocation(self):
        owner = self._owner()
        return None if owner is None else owner.GetWorldLocation()


class _GhostShip(_Ship):
    def GetNode(self):
        return _WeakNodeRef(self)


@pytest.fixture
def boot(tmp_path, monkeypatch):
    hum_allocator.reset_for_tests()
    engine_rumble.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "e.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()
    hum_allocator.reset_for_tests()
    engine_rumble.reset_for_tests()


def _stub_roster(monkeypatch, ships):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: list(ships))


def test_caps_at_four_nearest_ships(boot, monkeypatch):
    """Guide §10: the original caps this at 4; the reason is not established — keep it."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(7)]
    _stub_roster(monkeypatch, ships)

    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    humming = hum_allocator.humming_ship_names()
    assert len(humming) == 4
    assert humming == {"s0", "s1", "s2", "s3"}   # the four nearest


def test_ship_falling_out_of_top4_stops_humming(boot, monkeypatch):
    near = [_Ship(f"s{i}", x=i * 10) for i in range(4)]
    far = _Ship("far", x=500)
    _stub_roster(monkeypatch, near + [far])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "far" not in hum_allocator.humming_ship_names()

    # Listener travels out to the far ship; s3 (x=30) is now the odd one out.
    hum_allocator.update(listener_pos=(500.0, 0.0, 0.0))
    humming = hum_allocator.humming_ship_names()
    assert "far" in humming
    assert "s0" not in humming
    assert len(humming) == 4


def test_ships_without_an_impulse_engine_never_hum(boot, monkeypatch):
    """BC's gate: ShipClass with ship+0x2CC != 0 (the ImpulseEngine subsystem)."""
    _stub_roster(monkeypatch, [_NoEngine("rock", x=1), _Ship("ship", x=2)])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert hum_allocator.humming_ship_names() == {"ship"}


def test_update_is_idempotent_for_a_stable_roster(boot, monkeypatch):
    """A ship already in the top-4 must not be restarted every frame."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(3)]
    _stub_roster(monkeypatch, ships)
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert not plays, "a stable top-4 must not re-trigger play()"


def test_start_hum_while_muted_starts_silent(boot, monkeypatch):
    """Review finding #1 (mute leak): a ship entering the top-4 while the
    player is on the bridge (engine_rumble.set_muted(True)) must start at
    gain 0.0, not 1.0. Before this fix _start_hum never consulted
    engine_rumble._muted at all, so every top-4 boundary crossing during
    combat re-broke the bridge mute."""
    engine_rumble.set_muted(True)
    ship = _Ship("s0", x=10)
    _stub_roster(monkeypatch, [ship])

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    gains = [c["f"][0] for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_gain"]
    assert gains, "MUTE LEAK: new hum started at gain 1.0 while muted"
    assert gains[-1] == 0.0


def test_boundary_pair_jitter_does_not_thrash_hum(boot, monkeypatch):
    """Review finding #2 (boundary thrash): two ships hovering at near-equal
    range around the #4 cutoff (an ordinary combat formation) must not
    stop/restart their hum every frame just because their relative order
    jitters by a tiny amount.

    NOT claiming this is BC-faithful — the decompiled SetClass::UpdateSounds
    shows no deadband (see hum_allocator's module docstring). This proves our
    incumbent-wins hysteresis actually suppresses the churn a reviewer
    demonstrated without it: per-frame ops of
    [[], ['stop','play'], ['stop','play'], ...].
    """
    near = [_Ship(f"s{i}", x=i * 10) for i in range(3)]  # s0,s1,s2: solidly in
    b1 = _Ship("boundary_a", x=40.001)
    b2 = _Ship("boundary_b", x=39.999)
    ships = near + [b1, b2]
    _stub_roster(monkeypatch, ships)

    churn = []
    rosters_seen = []
    for i in range(6):
        # Jitter the boundary pair's relative order by ±0.001 each frame.
        if i % 2:
            b1._loc.x, b2._loc.x = 39.999, 40.001
        else:
            b1._loc.x, b2._loc.x = 40.001, 39.999
        _dauntless_host.audio.clear_command_log()
        hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
        ops = [c["op"] for c in _dauntless_host.audio.debug_command_log()
               if c["op"] in ("stop", "play")]
        churn.append(ops)
        rosters_seen.append(frozenset(hum_allocator.humming_ship_names()))

    # Frame 0 legitimately establishes the initial top-4; every later frame
    # must be silent despite the ±0.001 jitter, and the winning boundary ship
    # never changes once picked.
    assert all(not ops for ops in churn[1:]), churn
    assert len(set(rosters_seen)) == 1, rosters_seen


def test_ship_gc_without_teardown_stops_its_hum(boot, monkeypatch):
    """Review finding #3 (weakref leak): a ship dropped without going
    through ship_lifecycle.publish_destroyed (e.g. a mission-swap that tears
    down a set directly rather than destroying ships one at a time — the dev
    mission picker's swap path does this) must still have its looping AL
    source stopped, not leak a source that hums forever outside the cap."""
    ship = _GhostShip("ghost", x=5)
    # Close over a mutable holder, not `ship` itself, so we can drop the
    # roster's own reference to `ship` without touching the monkeypatch.
    roster_holder = [ship]
    monkeypatch.setattr(hum_allocator, "_roster", lambda: list(roster_holder))
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "ghost" in hum_allocator.humming_ship_names()

    _dauntless_host.audio.clear_command_log()
    roster_holder.clear()
    del ship
    gc.collect()

    ops = [c["op"] for c in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops, "ship GC'd without explicit teardown must still stop its hum"


def test_evicted_hum_is_restarted_on_next_update(boot, monkeypatch):
    """Review Critical #1 (live bug): `AudioSystem::play`'s pool-saturation
    eviction (native/src/audio/src/audio_system.cc) steals the lowest-
    priority playing source -- including a looping hum -- by calling
    `backend_->stop()` and erasing it from the C++ `sources_` map, WITHOUT
    ever telling Python. The Python-side `_PlayingSound._pid` stays truthy.

    Before this fix, `hum_allocator.update`'s `humming_ids` filtered on
    `_pid` alone, so an evicted hum's ship stayed in `_humming` (its dict key
    never dropped) and was therefore never restarted -- the ship would hum
    silently until it next happened to cross the top-4 boundary and get
    reconciled for an unrelated reason. That is the same failure shape as the
    warp bug this branch already fixed (1a355f3c), with a different trigger.

    `debug_mark_finished` simulates exactly what a dead-but-unreported
    handle looks like from Python's side: `is_finished(pid)` starts
    returning True (same observable effect as the C++ side erasing the
    source out from under `sources_` during eviction) while `_pid` itself
    is untouched -- there is no `Stop()` call, explicit or otherwise.
    """
    ship = _Ship("s0", x=10)
    _stub_roster(monkeypatch, [ship])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "s0" in hum_allocator.humming_ship_names()

    playing = hum_allocator._humming[ship]
    assert playing._pid, "sanity: the hum must actually be playing"
    _dauntless_host.audio.debug_mark_finished(playing._pid)

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert plays, (
        "an evicted/dead-but-still-in-_humming hum must be restarted on the "
        "next update() -- not left silently dead until an unrelated top-4 "
        "boundary crossing"
    )
    assert "s0" in hum_allocator.humming_ship_names()
    assert hum_allocator._humming[ship] is not playing, \
        "the stale dead handle must have been replaced by a fresh one"


def test_real_roster_finds_ship_via_iter_active_ships(boot):
    """Review finding #4: every other test in this file monkeypatches
    hum_allocator._roster, so the real production seam —
    _roster() -> iter_active_ships() -> set membership -> isinstance ShipClass
    — has zero coverage otherwise. This is the project's signature failure
    mode (green tests, silence in-game): if iter_active_ships silently
    yielded nothing, every other test here would stay green while no ship
    ever hums in the actual game."""
    import App
    from engine.appc.ships import ShipClass_Create
    from engine.appc.properties import ImpulseEngineProperty

    saved_sets = dict(App.g_kSetManager._sets)
    App.g_kSetManager._sets.clear()
    try:
        pSet = App.SetClass_Create()
        pSet.SetName("RealSet")
        ship = ShipClass_Create("real-ship")
        prop = ImpulseEngineProperty("Impulse Engines")
        prop.SetEngineSound("Federation Engines")
        ship.GetImpulseEngineSubsystem().SetProperty(prop)
        ship.SetTranslateXYZ(0.0, 0.0, 0.0)
        pSet.AddObjectToSet(ship, "real-ship")
        App.g_kSetManager._sets["RealSet"] = pSet

        hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

        assert hum_allocator.humming_ship_names() == {"real-ship"}
    finally:
        App.g_kSetManager._sets.clear()
        App.g_kSetManager._sets.update(saved_sets)
