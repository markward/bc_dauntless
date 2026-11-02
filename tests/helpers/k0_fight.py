"""A small scripted fight for the K0 charging kernel's tests (native weapon
state, Task 5; spec docs/superpowers/specs/2026-11-02-native-weapon-state-
design.md §4.3).

Each scenario runs twice on fresh real ships -- native combat off (today's
Python: `host_loop._advance_weapons` -> passive_weapons.advance) and on
(native_combat.k0_weapons: K0 steps every weapon, Python runs only its
records) -- and compares, after every tick, every weapon's charging and
reload state by float.hex() (types kept: a bool written where Python writes
an int differs) plus the ordered event log (ET_TORPEDO_RELOAD,
ET_CHARGE_TOGGLE, ET_WEAPON_FIRED, ET_TORPEDO_FIRED).

One tick is the host's order: the weapons' own update (`_advance_weapons`,
K0 on the native arm), then the held-weapon pump in a combat step block (K1
on the native arm), so banks fire, drain, deplete and recharge and tubes
fire and reload. Both run inside the combat effect queue's scope, opened in
BOTH arms (as the script before them, in its own): the queued weapon events
and sounds (spec 2026-11-02-combat-fire-events §4.2) are delivered at the
scope's end in both, so their handlers run at the same point and the one
event log compares (ruling F4; host_loop opens it with native combat on).
"""
import importlib
import math
import sys

import App

from engine import host_loop
from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import weapon_subsystems as ws
from engine.appc.math import TGMatrix3
from engine.core import step_memo

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0
GALAXY_VORCHA = (("Galaxy", "galaxy", (0.0, 0.0, 0.0), 0.0),
                 ("Vorcha", "vorcha", (10.0, 240.0, 5.0), math.pi))


def charge_toggle_type():
    import Conditions.ConditionPulseReady as cpr
    return cpr.ET_CHARGE_TOGGLE


def _load_hardpoint(ship, name):
    mod_name = "ships.Hardpoints." + name
    App.g_kModelPropertyManager.ClearLocalTemplates()
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)
    sys.modules[mod_name].LoadPropertySet(ship.GetPropertySet())
    ship.SetupProperties()


def groups(ship):
    return [g for g in (ship.GetPhaserSystem(), ship.GetPulseWeaponSystem(),
                        ship.GetTractorBeamSystem(), ship.GetTorpedoSystem())
            if g is not None]


def hx(v):
    """A value with its type; floats by .hex()."""
    if isinstance(v, float):
        return ("float", v.hex())
    return (type(v).__name__, v)


class World:
    """Real ships in one set, a pinned weapon clock, the event log."""

    def __init__(self, mp, native, tag, ships=GALAXY_VORCHA):
        nc.reset()
        if native:
            nc.configure(ON)
            assert nc.enabled()
        self.native = native
        self.mp = mp
        self.clock = [100.0]
        mp.setattr(ws, "_game_time", lambda: self.clock[0])
        self.set = App.SetClass_Create()
        self.tag = tag
        App.g_kSetManager.AddSet(self.set, tag)
        self.ships = {}
        for name, hardpoint, at, yaw in ships:
            ship = App.ShipClass_Create(name)
            _load_hardpoint(ship, hardpoint)
            ship.SetTranslateXYZ(*at)
            m = TGMatrix3()
            m.MakeZRotation(yaw)
            ship.SetMatrixRotation(m)
            self.set.AddObjectToSet(ship, name)
            self.ships[name] = ship
        self.order = list(self.ships.values())
        self.systems = [g for s in self.order for g in groups(s)]
        self.leaves = [g.GetWeapon(i) for g in self.systems
                       for i in range(g.GetNumWeapons())]
        self.labels = {id(s): s.GetName() for s in self.order}
        for g in self.systems:
            self.labels[id(g)] = "%s/%s" % (g.GetParentShip().GetName(),
                                            g.GetName())
        for w in self.leaves:
            self.labels[id(w)] = "%s/%s" % (
                w.GetParentSubsystem().GetParentShip().GetName(), w.GetName())
        self.n = 0
        self.log = []
        self.events = []
        self.hooks = []
        names = {App.ET_TORPEDO_RELOAD: "reload",
                 App.ET_WEAPON_FIRED: "fired",
                 App.ET_TORPEDO_FIRED: "torpedo_fired",
                 charge_toggle_type(): "charge_toggle"}
        orig = App.g_kEventManager.AddEvent

        def add_event(evt, _orig=orig):
            kind = names.get(evt.GetEventType())
            if kind is not None:
                self.events.append((kind, self.label(evt.GetSource()),
                                    self.label(evt.GetDestination()), self.n))
            result = _orig(evt)
            for hook in list(self.hooks):
                hook(evt)
            return result

        mp.setattr(App.g_kEventManager, "AddEvent", add_event)

    def label(self, obj):
        if obj is None:
            return None
        return self.labels.get(id(obj), type(obj).__name__)

    def weapons(self, ship_name, group_index):
        """The weapons of one group (0 phaser, 1 pulse, 2 tractor, 3
        torpedo), read from the ship's own attributes."""
        d = self.ships[ship_name].__dict__
        g = d[("_phaser_system", "_pulse_weapon_system",
               "_tractor_beam_system", "_torpedo_system")[group_index]]
        return [g.GetWeapon(i) for i in range(g.GetNumWeapons())]

    def close(self):
        App.g_kSetManager.DeleteSet(self.tag)

    def state(self, w):
        """One weapon's charging / reload state, every bit."""
        d = w.__dict__
        watcher = d.get("_charge_watcher")
        return (
            self.label(w),
            hx(d.get("_charge_level")), hx(d.get("_firing")),
            hx(d.get("_depleted")), hx(d.get("_beam_on_countdown")),
            hx(d.get("_cooldown_remaining")), hx(d.get("_num_ready")),
            tuple(hx(v) for v in d.get("_reload_timers", ())),
            tuple(hx(v) for v in d.get("_reload_advanced_at", ())),
            None if watcher is None else hx(watcher._value),
        )

    def record(self):
        self.log.append([self.state(w) for w in self.leaves])

    def tick(self, before=None):
        self.n += 1
        self.clock[0] += DT
        if before is not None:
            with effect_queue.scope():
                before(self)
        with effect_queue.scope():
            host_loop._advance_weapons(list(self.order), DT)
            with step_memo.combat_step():
                host_loop._pump_held_weapons(list(self.order), DT)
        self.record()


def run_both(mp_factory, script, ticks, ships=GALAXY_VORCHA, setup=None,
             passive=True):
    """`script(world, tick)` before each of `ticks` ticks, native off then
    on; every tick's state and the event log must be equal. Returns
    (reference world, native world, native counts).

    `passive=False` runs both arms with passive state off, so the reference
    is the per-tick model K0 reproduces call for call (with passive state
    on, an at-rest weapon's update is skipped, not called: the states are
    the same, but a test counting calls of an override would differ)."""
    from engine.appc import passive_state
    worlds = []
    counts = None
    for native in (False, True):
        with mp_factory() as mp:
            w = World(mp, native, "k0_%d" % native, ships)
            passive_state.configure(
                {} if passive else {"DAUNTLESS_PASSIVE_STATE": "0"})
            try:
                if setup is not None:
                    setup(w)
                for t in range(ticks):
                    w.tick(before=lambda w, t=t: script(w, t))
                if native:
                    counts = nc.counts()
                    nc.audit_mirror()
                    assert nc.audit_failures() == [], nc.audit_failures()
                    assert not nc._h.combat_k0_open()
            finally:
                w.close()
            worlds.append(w)
    ref, nat = worlds
    assert len(ref.log) == len(nat.log) == ticks
    for i, (a, b) in enumerate(zip(ref.log, nat.log), start=1):
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                i, x, y)
    assert nat.events == ref.events
    return ref, nat, counts
