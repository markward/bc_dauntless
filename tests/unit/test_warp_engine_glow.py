"""Host-loop wiring for the warp-nacelle glow.

Two pieces live here: the gate that decides WHICH ship (and which frame) gets a
warp-glow envelope, and the emitter-cache flag that marks a warp pod's light
emitters so they brighten alongside the pod's glow volume.

The gate is the subtle half. `WarpVFX` is a singleton but
`WarpSequence_Create` takes the flythrough branch for ANY ship with no player
check (see engine/appc/warp_state.py's module comment), so "the warp animator
is running" does NOT mean "the player is the one warping" — without the
registration check an NPC warping out would light the player's nacelles.
"""
import pytest

from engine import host_loop, warp_vfx
from engine.appc import warp_state


class _Ship:
    pass


@pytest.fixture
def clean_warp():
    """Leave the warp singleton and flythrough registry as we found them."""
    warp_vfx.get().stop()
    warp_state.reset()
    yield
    warp_vfx.get().stop()
    warp_state.reset()


def test_no_envelope_when_no_warp_is_running(clean_warp):
    ship = _Ship()
    warp_state.begin_flythrough(ship)
    assert host_loop._warp_glow_envelope(ship) is None


def test_envelope_while_the_ship_is_flying_its_warp(clean_warp):
    ship = _Ship()
    warp_state.begin_flythrough(ship)
    w = warp_vfx.get()
    w.start((0.0, 1.0, 0.0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(2.0)                                  # the jump
    assert host_loop._warp_glow_envelope(ship) == (1.0, 1.0)


def test_an_npcs_warp_does_not_light_another_ships_nacelles(clean_warp):
    # The animator is running, but for the NPC — the player is not registered,
    # so the player's nacelles must stay dark.
    npc, player = _Ship(), _Ship()
    warp_state.begin_flythrough(npc)
    w = warp_vfx.get()
    w.start((0.0, 1.0, 0.0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(2.0)
    assert host_loop._warp_glow_envelope(npc) == (1.0, 1.0)
    assert host_loop._warp_glow_envelope(player) is None


def test_no_envelope_for_none(clean_warp):
    warp_vfx.get().start((0.0, 1.0, 0.0), 2.0, 4.0, 0.0)
    warp_vfx.get().tick(2.0)
    assert host_loop._warp_glow_envelope(None) is None


# --- emitter cache -------------------------------------------------------

def _point_prop():
    from engine.appc.properties import SubsystemProperty
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, "point")
    p.SetLightEmitterPosition(0, 0.0, 0.0, 0.0)
    p.SetLightEmitterAxis(0, 0.0, -1.0, 0.0)
    p.SetLightEmitterLength(0, 0.0)
    p.SetLightEmitterRadius(0, 3.0)
    p.SetLightEmitterColor(0, 1.0, 0.5, 0.25)
    p.SetLightEmitterIntensity(0, 2.5)
    return p


class _Pod:
    def __init__(self):
        self._prop = _point_prop()
    def GetProperty(self): return self._prop
    def GetName(self): return "pod"
    def GetNumChildSubsystems(self): return 0


class _Agg:
    def __init__(self, kids): self._kids = kids
    def GetNumChildSubsystems(self): return len(self._kids)
    def GetChildSubsystem(self, i): return self._kids[i]


def test_emitter_cache_marks_warp_pod_emitters(monkeypatch):
    warp_pod, impulse_pod, other = _Pod(), _Pod(), _Pod()

    class _S:
        def GetWarpEngineSubsystem(self): return _Agg([warp_pod])
        def GetImpulseEngineSubsystem(self): return impulse_pod
    ship = _S()
    monkeypatch.setattr("engine.ui.ship_property_viewer._iter_subsystems",
                        lambda s: [warp_pod, impulse_pod, other])

    entries = host_loop._build_ship_emitter_cache(ship)
    flags = {e[0]: (e[1], e[2]) for e in entries}      # sub -> (is_impulse, is_warp)
    assert flags[warp_pod] == (False, True)
    assert flags[impulse_pod] == (True, False)
    assert flags[other] == (False, False)
