"""No kernel hands damage back to Python (native damage, Task 4; spec
docs/superpowers/specs/2026-11-02-native-damage-design.md §3 goal 2, §6
"Kernel guard").

The 64-ship combat_stress fight, switch on, fought by its AI through
GameLoop.tick and driven the host's way (per tick `_advance_weapons` +
`_advance_combat` inside the tick's scope, then the boundary). Every K2 record
is tallied by kind as the kernel returns it, and every torpedo hit
`projectiles.update_all` hands to host_loop's hit loop is counted:

- K2 applies each damage pulse in the walk: no CONTACT record, ever;
- K3 applies its hits itself, after the step's expiries: update_all returns
  none to host_loop, and run_k3 hands none to Python;

while pulses and torpedo hits really happened, natively, with no native
damage call falling back. The per-tick record counts by kind are printed
(the report's before/after table)."""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import native_combat as nc
from engine.appc import projectiles
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, headless_mission

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k2_next"),
    reason="native combat bindings not built")

SHIPS = "64"
TICKS = 1800
SEED = 20261102
RADIUS = 4.0


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


def test_no_kernel_hands_damage_back(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
    monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)
    nc.reset()
    App.g_kTimerManager._time = 0.0
    random.seed(0)
    headless_mission.clear_in_flight()
    headless_mission.load("engine.dev_missions.combat_stress")
    host_loop._reset_sensor_state()
    step_memo.forget()
    nc.configure({"DAUNTLESS_NATIVE_COMBAT": "1"})
    assert nc.enabled()
    player = App.Game_GetCurrentPlayer()
    ships = list(iter_ships())
    assert len(ships) == int(SHIPS) + 1
    # Headless ships have radius 0, so no torpedo could touch one (the K3
    # differential's note): combat_stress's nominal hull on every ship.
    for s in ships:
        s.SetRadius(RADIUS)

    kinds = {v: k for k, v in _h.combat_k2_kinds().items()}
    tally = {}
    k2_next = _h.combat_k2_next

    def next_spy():
        rec = k2_next()
        tally[kinds[rec[0]]] = tally.get(kinds[rec[0]], 0) + 1
        return rec

    monkeypatch.setattr(_h, "combat_k2_next", next_spy)
    handed = {"k3_hits": 0}
    update_all = projectiles.update_all

    def update_spy(dt, all_ships, *, ship_instances=None):
        hits = update_all(dt, all_ships, ship_instances=ship_instances)
        handed["k3_hits"] += len(hits)
        return hits

    monkeypatch.setattr(projectiles, "update_all", update_spy)

    # Constructing a GameLoop re-reads the environment.
    monkeypatch.setenv("DAUNTLESS_NATIVE_COMBAT", "1")
    loop = game_loop.GameLoop()
    assert nc.enabled()
    random.seed(SEED)
    for tick in range(TICKS):
        loop.tick()
        live = list(iter_ships())
        with host_loop._combat_effect_scope():
            host_loop._advance_weapons(live, TICK_DELTA)
            host_loop._advance_combat(live, TICK_DELTA, player=player,
                                      push_render_data=False)
        host_loop._combat_tick_boundary()

    c = nc.counts()
    dmg = nc.damage_counts()
    per_tick = {k: round(n / TICKS, 4) for k, n in sorted(tally.items())}
    print("\nK2 records per tick by kind:", per_tick)
    print("K3 hits handed to host_loop: %d (%.4f per tick)"
          % (handed["k3_hits"], handed["k3_hits"] / TICKS))
    print("native damage:", dmg)
    print("k2:", {k: v for k, v in c.items() if k.startswith("k2_")})
    print("k3:", {k: v for k, v in c.items() if k.startswith("k3_")})

    # Pulses and torpedo hits really happened, in the kernels.
    pulses = tally.get("CONTACT", 0) + c.get("k2_native_pulses", 0)
    hits = (handed["k3_hits"] + c.get("k3_native_hits", 0)
            + c.get("k3_hit_python", 0))
    assert pulses > 0 and hits > 0, (pulses, hits)
    assert c["k2_python_steps"] == 0, c
    assert c["k3_python_steps"] == 0, c
    # The guard: no damage pulse comes back as a record, no torpedo hit is
    # handed to Python.
    assert tally.get("CONTACT", 0) == 0, tally
    assert handed["k3_hits"] == 0, handed
    assert c["k3_hit_python"] == 0, c
    assert c["k2_pulse_python"] == 0, c
    assert c["k2_native_pulses"] > 0 and c["k3_native_hits"] > 0, c
    assert dmg["fallbacks"] == 0, dmg
