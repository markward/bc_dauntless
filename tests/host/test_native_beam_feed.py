"""Native per-frame beam descriptor feed (phase 6 follow-up 1): the oracle.

Task 1: `_h.phaser_beams_debug()` / `tractor_beams_debug()` read back what
`set_phaser_beams` / `set_tractor_beams` pushed, so a later native feed can be
compared bit for bit against today's Python builders.
"""
import struct

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "set_phaser_beams"),
    reason="native host not built")


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


FULL = {
    "emitter": (1.1, 2.2, 3.3), "target": (4.4, 5.5, 6.6),
    "color": (0.1, 0.2, 0.3, 0.4), "width": 0.7, "u_tiles": 3.3,
    "num_sides": 12, "taper_radius": 0.02, "taper_ratio": 0.3,
    "taper_min_length": 4.4, "taper_max_length": 31.1,
    "perimeter_tile": 2.2, "texture_speed": 1.7, "end_width_scale": 1.25,
}
MINIMAL = {
    "emitter": (0.5, 0.25, 0.125), "target": (7.7, 8.8, 9.9),
    "color": (1.0, 0.9, 0.8, 0.7), "width": 0.3,
}


def packed(d):
    """The descriptor `d` as the native side must hold it: defaults applied,
    float32-rounded, packed bytes (so -0.0 / NaN cannot hide in a float ==)."""
    return struct.pack(
        PACK, *d["emitter"], *d["target"], *d["color"], d["width"],
        d.get("u_tiles", 1.0), d.get("num_sides", 6),
        d.get("taper_radius", 0.01), d.get("taper_ratio", 0.25),
        d.get("taper_min_length", 5.0), d.get("taper_max_length", 30.0),
        d.get("perimeter_tile", 1.0), d.get("texture_speed", 0.0),
        d.get("end_width_scale", 1.0))


PACK = "<12f i 7f"


def test_readback_returns_what_set_phaser_beams_pushed():
    _h.set_phaser_beams([FULL, MINIMAL])
    _h.set_tractor_beams([MINIMAL, FULL])
    try:
        assert _beams("phaser") == [packed(FULL), packed(MINIMAL)]
        assert _beams("tractor") == [packed(MINIMAL), packed(FULL)]
        # No end_width_scale given: the native default is 1.0.
        assert struct.unpack(PACK, _beams("phaser")[1])[-1] == 1.0
        assert len(_h.phaser_beams_debug()[0]) == 20
    finally:
        _h.set_phaser_beams([])
        _h.set_tractor_beams([])


# ── The scene: real instances, phasers firing, a tractor towing ─────────────

from tests.host.test_native_k2_differential import (  # noqa: E402,F401
    ON, TICKS, _Scene, _hermetic, host)

def _beams(kind):
    """The pushed descriptors of `kind` ('phaser' | 'tractor') as packed
    bytes, one per beam, so a compare is bitwise."""
    rows = getattr(_h, kind + "_beams_debug")()
    return [struct.pack(PACK, *r) for r in rows]


def _python_feed(ships, ship_instances):
    """Today's Python builders for both beam kinds (sharing one _ViewMemo),
    pushed through host_io; returns (_beams('phaser'), _beams('tractor'))."""
    from engine import host_io, host_loop
    memo = host_loop._ViewMemo()
    host_io.set_phaser_beams(host_loop._build_phaser_beam_render_data(
        ships, ship_instances=ship_instances, memo=memo))
    host_io.set_tractor_beams(host_loop._build_tractor_beam_render_data(
        ships, ship_instances=ship_instances, memo=memo))
    return _beams("phaser"), _beams("tractor")


class BeamScene:
    """combat_stress on the real host (native combat on), every ship realised.
    `ships`, `ship_instances`, `scene` (the K2 _Scene) and `advance()`."""

    def __init__(self, scene):
        self.scene = scene
        self.ships = scene.ships
        self.ship_instances = scene.session.ship_instances
        self.player = scene.player

    def advance(self, ticks=1):
        """One frame of `ticks` sim ticks, as the K2 differential runs one:
        render sync, subsystem update, weapons + combat per tick."""
        import App
        from engine.appc.ship_iter import iter_ships
        from engine.core import loop as game_loop
        from engine.core.loop import TICK_DELTA
        from engine import host_loop
        sc = self.scene
        sc.sync_render()
        for _ in range(ticks):
            App.g_kTimerManager._time += TICK_DELTA
            game_loop._update_ship_subsystems()
        for _ in range(ticks):
            sc.tick += 1
            ships = list(iter_ships())
            with host_loop._combat_effect_scope():
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(
                    ships, TICK_DELTA, ship_instances=self.ship_instances,
                    player=self.player, push_render_data=False)
            host_loop._combat_tick_boundary()

    def _open_fire(self):
        sc = self.scene
        # Sensors power up at 1.0 s of game time.
        self.advance(ticks=70)
        # Spread targets so both shield states, hull traces and bubble
        # entries are all exercised.
        for i, g in enumerate(sc.systems):
            g.TurnOn()
            g.SetSingleFire(0)
            foes = sc._foes(g.GetParentShip())
            g.StartFiring(foes[i % len(foes)] if foes else None)
        # Shields: one foe up, one down.
        foes = sc._foes(self.player)
        for i, s in enumerate(foes):
            sh = s.GetShieldSubsystem()
            if sh is not None:
                (sh.TurnOn if i % 2 == 0 else sh.TurnOff)()
        # One tractor tows.
        for s in sc.ships:
            tb = s.GetTractorBeamSystem()
            foes = sc._foes(s)
            if tb is not None and foes:
                tb.TurnOn()
                tb.StartFiring(foes[0], None)
                break


@pytest.fixture
def beam_scene(monkeypatch, host):
    scene = _Scene(monkeypatch, host, ON)
    try:
        bs = BeamScene(scene)
        bs._open_fire()
        for _ in range(30):
            bs.advance()
        yield bs
    finally:
        scene.close()


def _foe_shield_states(scene):
    return {s.GetName(): bool(s.GetShieldSubsystem().IsOn())
            for s in scene._foes(scene.player)
            if s.GetShieldSubsystem() is not None}


def _phaser_targets_by_shield(bs):
    """{shields_up: count of ships' firing banks aimed at such a target}
    over ships whose builder output is non-empty."""
    from engine import host_loop
    seen = {True: 0, False: 0}
    for ship in bs.ships:
        if not host_loop._build_phaser_beam_render_data(
                [ship], ship_instances=bs.ship_instances):
            continue
        for bank in host_loop._firing_banks(ship.GetPhaserSystem()):
            sh = getattr(bank._target, "GetShieldSubsystem",
                         lambda: None)()
            if sh is not None:
                seen[bool(sh.IsOn())] += 1
    return seen


def test_scene_feeds_phaser_and_tractor_pairs(beam_scene):
    before = _foe_shield_states(beam_scene.scene)
    got, seen = None, {True: 0, False: 0}
    for _ in range(60):
        beam_scene.advance()
        got = _python_feed(beam_scene.ships, beam_scene.ship_instances)
        seen = _phaser_targets_by_shield(beam_scene)
        if got[0] and got[1] and all(seen.values()):
            break
    phasers, tractors = got
    # Every firing bank emits an outer shell + inner core pair.
    assert len(phasers) > 0 and len(phasers) % 2 == 0
    assert len(tractors) > 0 and len(tractors) % 2 == 0
    after = _foe_shield_states(beam_scene.scene)
    assert set(before.values()) == {True, False}, before
    assert set(after.values()) == {True, False}, after
    assert seen[True] > 0 and seen[False] > 0, (
        "phasers must land on a shields-up and a shields-down foe: %r" % seen)
