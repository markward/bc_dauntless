"""The combat step with native can_detect is bit-identical to the Python
(native combat phase 1a, Task 7; spec
docs/superpowers/specs/2026-10-30-native-combat-step-design.md §3.2, §5).

Three fresh loads of combat_stress -- the Python reference
(``DAUNTLESS_NATIVE_COMBAT=0``), native (``=1``) and native under the audit
(``DAUNTLESS_NATIVE_AUDIT=1``) -- get the same seeded stream of operations,
all through public SDK calls: sensors TurnOff / TurnOn / SetCondition,
StartCloaking / StopCloaking, StartFiring / StopFiring. Every tick each
weapon's and weapon system's (IsFiring, target is None), every ship pair's
lock-break latch, and the fired / torpedo-fired / hit events in order are
compared with ``==``. Under the audit nothing may be recorded, per call or in
the whole mirror (audited every tick, as GameLoop.tick does).

Driven the host's way, without GameLoop.tick (AI draws on the unseeded
module ``random``): per frame, ops, N subsystem ticks, ops, then N combat
ticks of host_loop._advance_weapons + host_loop._advance_combat (each one
step_memo block), with a few ops between them, then the player's contact
pass. With 6 ticks a frame, several combat steps run at the same final game
time, so native answers must stay frozen exactly as long as the Python's
(review focus 4).
"""
import random

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import native_combat as nc
from engine.appc import sensor_contacts
from engine.appc import sensor_detection as sd
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core import step_memo
from engine.core.loop import TICK_DELTA
from tests.helpers import bc_assets, headless_mission

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_can_detect"),
    reason="native combat bindings not built")

SHIPS = "6"
TICKS = 600
SEED = 20261031

OFF = {"DAUNTLESS_NATIVE_COMBAT": "0"}
ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
AUDIT = {"DAUNTLESS_NATIVE_AUDIT": "1"}
ARMS = (("off", OFF), ("on", ON), ("audit", AUDIT))


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


def _groups(ship):
    return [g for g in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                        ship.GetTractorBeamSystem(), ship.GetTorpedoSystem())
            if g is not None]


class _Scene:
    def __init__(self, mp, env):
        mp.delenv("DAUNTLESS_NATIVE_COMBAT", raising=False)
        mp.delenv("DAUNTLESS_NATIVE_AUDIT", raising=False)
        mp.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)
        nc.reset()
        App.g_kTimerManager._time = 0.0
        random.seed(0)
        headless_mission.load("engine.dev_missions.combat_stress")
        host_loop._reset_sensor_state()
        step_memo.forget()
        # After the load: constructing a GameLoop re-reads the environment.
        nc.configure(env)
        assert nc.enabled() is (env is not OFF)
        self.player = App.Game_GetCurrentPlayer()
        self.ships = list(iter_ships())
        assert len(self.ships) == int(SHIPS) + 1
        # Weapon groups that can fire (a tractor never shoots an enemy).
        self.firing = [g for s in self.ships for g in _groups(s)
                       if g is not s.GetTractorBeamSystem()]
        self.systems = [g for s in self.ships for g in _groups(s)]
        self.weapons = [g.GetWeapon(i) for g in self.systems
                        for i in range(g.GetNumWeapons())]
        self.sensors = [s.GetSensorSubsystem() for s in self.ships
                        if s.GetSensorSubsystem() is not None]
        self.cloaks = [s.GetCloakingSubsystem() for s in self.ships
                       if s.GetCloakingSubsystem() is not None]
        assert self.sensors and self.cloaks
        self.tick = 0
        self.log = []
        self.events = []
        names = {App.ET_WEAPON_FIRED: "fired",
                 App.ET_TORPEDO_FIRED: "torpedo_fired",
                 App.ET_WEAPON_HIT: "hit"}
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            kind = names.get(evt.GetEventType())
            if kind is not None:
                dest = evt.GetDestination()
                self.events.append((kind, _name(dest), self.tick))
            return _orig(evt)

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def _enemy_of(self, rng, ship):
        side = ship.GetName().startswith("Enemy")
        foes = [s for s in self.ships
                if s.GetName().startswith("Enemy") != side]
        return rng.choice(foes)

    def op(self, rng):
        kind = rng.choice(OPS)
        if kind == "fire":
            group = rng.choice(self.firing)
            group.StartFiring(self._enemy_of(rng, group.GetParentShip()))
        elif kind == "stop":
            rng.choice(self.firing).StopFiring()
        elif kind == "sensor_off":
            rng.choice(self.sensors).TurnOff()
        elif kind == "sensor_on":
            rng.choice(self.sensors).TurnOn()
        elif kind == "sensor_condition":
            sub = rng.choice(self.sensors)
            sub.SetCondition(sub.GetMaxCondition()
                             * rng.choice((0.0, 0.1, 0.3, 0.6, 1.0, 1.0)))
        elif kind == "cloak":
            rng.choice(self.cloaks).StartCloaking()
        elif kind == "decloak":
            rng.choice(self.cloaks).StopCloaking()
        else:
            raise AssertionError(kind)

    def ops(self, rng, n):
        for _ in range(n):
            self.op(rng)

    def record(self):
        row = [(g.IsFiring(), g._target is None, g._held_target is None)
               for g in self.systems]
        row += [(w.IsFiring(), getattr(w, "_target", None) is None)
                for w in self.weapons]
        row += [sd._latched(a, b) for a in self.ships for b in self.ships
                if a is not b]
        self.log.append(row)
        if nc.audit_enabled():
            nc.audit_mirror()           # what GameLoop.tick does under audit

    def run(self, ticks_per_frame):
        rng = random.Random(SEED)
        while self.tick < TICKS:
            self.ops(rng, rng.randint(0, 2))
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            self.ops(rng, rng.randint(0, 2))
            for _ in range(ticks_per_frame):
                self.tick += 1
                ships = list(iter_ships())
                host_loop._advance_weapons(ships, TICK_DELTA)
                host_loop._advance_combat(ships, TICK_DELTA,
                                          player=self.player,
                                          push_render_data=False)
                self.record()
                if rng.random() < 0.3:
                    self.op(rng)
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        return self.log, self.events


# Weighted toward firing, so the fight goes on while sensors and cloaks
# change who can detect whom.
OPS = ("fire",) * 8 + ("stop", "sensor_off", "sensor_on", "sensor_on",
                       "sensor_condition", "cloak", "decloak", "decloak")


def _name(obj):
    return obj.GetName() if obj is not None and hasattr(obj, "GetName") \
        else None


@pytest.mark.parametrize("ticks_per_frame", (1, 6))
def test_combat_step_matches_python(monkeypatch, ticks_per_frame):
    runs, counts = {}, {}
    failures = None
    for name, env in ARMS:
        with monkeypatch.context() as mp:
            runs[name] = _Scene(mp, env).run(ticks_per_frame)
            if env is AUDIT:
                failures = list(nc.audit_failures())
            counts[name] = nc.counts()
    ref_log, ref_events = runs["off"]
    kinds = {e[0] for e in ref_events}
    assert {"fired", "hit"} <= kinds, kinds
    for name in ("on", "audit"):
        log, events = runs[name]
        assert len(log) == len(ref_log) == TICKS
        for tick, (row, ref_row) in enumerate(zip(log, ref_log), start=1):
            assert row == ref_row, "%s: state differs at tick %d" % (name, tick)
        assert events == ref_events, name
    assert failures == [], failures
    assert counts["off"]["native_calls"] == 0, counts
    assert counts["on"]["native_calls"] > 0, counts
    assert counts["audit"]["native_calls"] > 0, counts
    print("native-combat-step counts (tpf=%d):" % ticks_per_frame, counts,
          "events:", len(ref_events))
