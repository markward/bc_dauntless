"""Native K0 charging and reloading is bit-identical to the Python in a
headless fight (native weapon state, Task 6; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §5, plan
docs/superpowers/plans/2026-11-02-native-weapon-state.md Review Focus 4).

Two fresh loads of combat_stress -- the Python reference
(``DAUNTLESS_NATIVE_COMBAT=0``: host_loop._advance_weapons' passive walk)
and native (``=1``: K0 steps every weapon from the mirror, Python runs only
its records; K1 / K2 / K3 run the fight around it) -- get the same seeded
stream of operations through public calls: the K1 differential's fight
(tests/helpers/k1_fight.py, whose scene this
extends) plus the writes K0's inputs see: charges set (NaN and -0.0
included), banks refilled, tractors drained, tubes fired, unloaded and
loaded by hand, weapon systems' power wanted and the phaser power level
changed, weapons worn to any condition. Every tube's reload delay is
shortened and every pulse cannon's watcher carries a range check (as
Conditions/ConditionPulseReady registers one), so tubes reload and watchers
post ET_CHARGE_TOGGLE inside the run.

After every tick, every weapon's charging and reload state is compared by
.hex() with its type (`_charge_level`, `_firing`, `_depleted`,
`_beam_on_countdown`, `_cooldown_remaining`, `_num_ready`, both slot lists,
the watcher's value) and by IDENTITY (whether each slot list and the
watcher are the object they were last tick: K0 writes slots in place, as
UpdateReload does), on top of the K1 differential's own record. Every
ET_TORPEDO_RELOAD, ET_CHARGE_TOGGLE and ET_WEAPON_FIRED is logged, in
order; the queued kinds also compare per tick as an ordered list of their
own (tests/helpers/effect_split.py, the K1 scene's). A launch's
ET_WEAPON_FIRED is also logged where it is POSTED (the producer's call
that acts, `_post_weapon_fired` with nothing deferring), with the state of
every weapon of its ship when the op or the tick step that produced it
ends: the moment both arms share. Since launch deferral a tube's, a dumb
fire's and a cannon's launch is the kernel's (a SPAWN, posted when the
queue is delivered at the end of the step, or of a K1 session an op's
StartFiring ran), so the native arm has no Python call where the reference
produced it, and the weapons' state there is the kernel's. K0's own
reloads and watcher crossings have no Python producer to spy since combat
fire events Task 4 (the kernel logs the writes and queues TORPEDO_RELOAD /
WATCH itself), as K1's beam edges since Task 3: their writes are in the
per-tick record and their events in the queued list, and the native arm's
tallies (k0_logged, k0_entries) must account for every one.

Review Focus 4: with three ticks a frame the host's three K0 sessions run
back to back on one game clock; the tubes credit the whole frame in the
first session and nothing in the next two, exactly as Python.
"""
import math

import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

from engine import host_loop
from engine.appc import effect_queue
from engine.appc import native_combat as nc
from engine.appc import weapon_subsystems as ws
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.ship_iter import iter_ships
from engine.core import loop as game_loop
from engine.core.loop import TICK_DELTA
from engine.appc import sensor_contacts
from tests.helpers import bc_assets, effect_split
from tests.helpers.k0_fight import charge_toggle_type
from tests.helpers.k3_fight import check_weapon_state_paths
from tests.helpers import k1_fight as k1d

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k0_next"),
    reason="native K0 bindings not built")

TICKS = 480
# Stock ReloadDelay is tens of seconds, longer than the run; shortened alike
# in both arms so tubes reload (and post ET_TORPEDO_RELOAD) inside it.
RELOAD_DELAY_S = 0.6
CHARGE_TOGGLE_FRACTION = 0.6


@pytest.fixture(autouse=True)
def _needs_assets_and_hermetic_mods(monkeypatch, tmp_path):
    bc_assets.require_game_dir("data/Models/Ships/Galaxy")
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    nc.reset()


def _hx(v):
    return k1d._t(v)


class _K0Scene(k1d._Scene):
    """The K1 differential's scene, with K0's inputs in play and K0's state
    recorded."""

    def __init__(self, mp, env, ships="8"):
        super().__init__(mp, env, ships=ships)
        self.scopes = effect_split.Scopes(mp)
        self.toggle = charge_toggle_type()
        self.k0_kinds = {App.ET_TORPEDO_RELOAD: "reload",
                         self.toggle: "charge_toggle",
                         App.ET_WEAPON_FIRED: "fired"}
        self.tubes = [w for w in self.weapons if isinstance(w, ws.TorpedoTube)]
        self.chargers = [w for w in self.weapons
                         if isinstance(w, ws._EnergyWeaponFireMixin)]
        self.tractors = [w for w in self.weapons
                         if isinstance(w, ws.TractorBeam)]
        self.phaser_systems = [g for g in self.systems
                               if isinstance(g, ws.PhaserSystem)]
        for tube in self.tubes:
            tube._reload_delay = RELOAD_DELAY_S
        for w in self.weapons:
            if isinstance(w, ws.PulseWeapon):
                evt = App.TGEvent_Create()
                evt.SetEventType(self.toggle)
                evt.SetDestination(w)
                w.GetChargeWatcher().AddRangeCheck(
                    CHARGE_TOGGLE_FRACTION, App.FloatRangeWatcher.FRW_BOTH,
                    evt)
        self.k0_log = []        # per tick: (now, [weapon state])
        self.k0_events = []     # (kind, source, destination, tick)
        # (kind, weapon, tick, "op" / "step", its ship's weapons' state when
        # that op or step ended) per production; `_pending` holds the
        # productions of the op or step still running.
        self.k0_produced = []
        self._pending = []
        self.held_lists = {}    # id(weapon) -> (timers, advanced, watcher)
        self.watch_checked = 0  # native arm: watchers compared with the row
        self.watch_mismatch = []
        self.odd = {}           # odd charges written, by repr
        self._spy_producers(mp)

    def _spy_producers(self, mp):
        """A launch's ET_WEAPON_FIRED, logged where it is POSTED: the
        producer's call with nothing deferring -- the reference's own, at
        once; the native arm's at the delivery of the queue (a kernel
        launch's SPAWN or WEAPON_FIRED, or Python's entry, appended by the
        same producer while deferring, which is not logged). The ship's
        weapons' state is taken when the op or step ends (`_settle`): where
        the reference produced it mid-step the native arm ran no Python
        (launch deferral). Not a beam's edge (K1 queues it natively since
        combat fire events Task 3), nor K0's reloads and watcher crossings
        (K0 queues them natively since Task 4): no Python call to spy, and a
        spy on TorpedoTube._broadcast_reload or FloatRangeWatcher._update
        would be a class patch K0's override guard obeys by handing the
        weapons back."""
        fired = ws._post_weapon_fired

        def fired_spy(weapon, target, _orig=fired):
            if (not isinstance(weapon, ws.PhaserBank)
                    and not effect_queue.deferring()):
                self._pending.append(("fired", weapon, self.tick))
            return _orig(weapon, target)

        mp.setattr(ws, "_post_weapon_fired", fired_spy)

    def _settle(self, where):
        """The op or step that just ended: log its productions with their
        ships' weapons' state now."""
        for kind, weapon, tick in self._pending:
            self.k0_produced.append((kind, self.label(weapon), tick, where,
                                     self.ship_state(weapon)))
        self._pending = []

    # ── Record ───────────────────────────────────────────────────────────────

    def k0_state(self, w):
        d = w.__dict__
        watcher = d.get("_charge_watcher")
        return (self.label(w),
                _hx(d.get("_charge_level")), _hx(d.get("_firing")),
                _hx(d.get("_depleted")), _hx(d.get("_beam_on_countdown")),
                _hx(d.get("_cooldown_remaining")), _hx(d.get("_num_ready")),
                tuple(_hx(v) for v in d.get("_reload_timers", ())),
                tuple(_hx(v) for v in d.get("_reload_advanced_at", ())),
                None if watcher is None else _hx(watcher._value))

    def ship_of(self, obj):
        sub = getattr(obj, "GetParentSubsystem", None)
        system = sub() if sub is not None else None
        return None if system is None else system.GetParentShip()

    def ship_state(self, weapon):
        """The state of every weapon of `weapon`'s ship."""
        ship = self.ship_of(weapon)
        return tuple(self.k0_state(w) for w in self.weapons
                     if ship is not None and self.ship_of(w) is ship)

    def payload(self, evt):
        """K1's payload; K0's events are logged (k0_events) too. A
        launch's is logged with its ship's weapons' state too
        (k0_produced)."""
        base = super().payload(evt)
        kind = self.k0_kinds.get(evt.GetEventType())
        if kind is None:
            return base
        self.k0_events.append((kind, self.label(evt.GetSource()),
                               self.label(evt.GetDestination()), self.tick))
        return (base, kind)

    def record(self):
        self._settle("step")
        super().record()
        if self.native:
            # K0's WATCH carries old = the mirrored `_watch_value`: every
            # tick it must be the owned watcher's committed `_value`.
            for w in self.weapons:
                watcher = w.__dict__.get("_charge_watcher")
                h = w.__dict__.get("_nslot")
                if h is None or not nc._owns_watcher(w, watcher):
                    continue
                self.watch_checked += 1
                got = _h.combat_dump(h)["_watch_value"]
                if float(got).hex() != watcher._value.hex():
                    self.watch_mismatch.append(
                        (self.tick, self.label(w), watcher._value, got))
        row = []
        for w in self.weapons:
            d = w.__dict__
            lists = (d.get("_reload_timers"), d.get("_reload_advanced_at"),
                     d.get("_charge_watcher"))
            prev = self.held_lists.get(id(w))
            # Which of the slot lists and the watcher is a NEW object since
            # last tick (the previous ones are held: ids never reused).
            same = None if prev is None else tuple(
                a is b for a, b in zip(lists, prev))
            self.held_lists[id(w)] = lists
            row.append(self.k0_state(w) + (same,))
        self.k0_log.append((App.g_kUtopiaModule.GetGameTime(), row))

    # ── Ops ──────────────────────────────────────────────────────────────────

    def op(self, rng, ops):
        self._op(rng, ops)
        self._settle("op")

    def _op(self, rng, ops):
        kind = rng.choice(ops)
        if kind == "charge":
            w = rng.choice(self.chargers)
            w.SetChargeLevel(rng.random() * w.GetMaxCharge())
        elif kind == "odd_charge":
            # NaN and -0.0 are stored as given (SetChargeLevel's `v < 0.0`
            # and `v > max` are both false). A lit bank drains NaN to 0.0
            # through max(0.0, ...) (and latches depleted); an idle one keeps
            # it (its headroom is NaN). A -0.0 is kept by a bank whose
            # system is off (no recharge), so half the time one is picked.
            v = rng.choice((math.nan, -0.0, 0.0))
            lit = [w for w in self.chargers if w.__dict__.get("_firing")]
            off = [w for w in self.chargers
                   if not w.GetParentSubsystem().IsOn()]
            pool = (lit if math.isnan(v) else off) if rng.random() < 0.5 \
                else self.chargers
            w = rng.choice(pool or self.chargers)
            w.SetChargeLevel(v)
            self.odd[repr(v)] = self.odd.get(repr(v), 0) + 1
        elif kind == "recharge_all":
            # Actions/ShipScriptActions.py:362,369
            for w in self.chargers:
                w.SetChargeLevel(w.GetMaxCharge())
        elif kind == "tractor_drain":
            w = rng.choice(self.tractors)
            w.SetChargeLevel(w.GetMaxCharge() * rng.choice((0.0, 0.3)))
        elif kind == "tube_fire":
            tube = rng.choice(self.tubes)
            ship = tube.GetParentSubsystem().GetParentShip()
            tube.Fire(self._enemy_of(rng, ship) if rng.random() < 0.5
                      else None)
        elif kind == "tube_dec":
            rng.choice(self.tubes).DecNumReady()
        elif kind == "tube_set":
            tube = rng.choice(self.tubes)
            tube.SetNumReady(rng.randint(0, tube.GetMaxReady()))
        elif kind == "sys_power":
            # Fractions whose products round differently by operand order
            # (rate * power * condition), as well as the round ones.
            rng.choice(self.systems).SetPowerPercentageWanted(
                rng.choice((0.0, 0.5, 1.0, 1.25, rng.uniform(0.3, 1.25))))
        elif kind == "worn":
            w = rng.choice(self.chargers)
            w.SetCondition(w.GetMaxCondition() * rng.uniform(0.05, 1.0))
        elif kind == "phaser_level":
            rng.choice(self.phaser_systems).SetPowerLevel(rng.randint(0, 2))
        else:
            super().op(rng, (kind,))

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self, ticks_per_frame, ops, mid_ops, ticks=TICKS):
        """The K1 scene's host order (ops, N subsystem ticks, ops, N weapon
        and combat steps, each maybe followed by an op from `mid_ops`)."""
        import random
        rng = random.Random(k1d.SEED)
        while self.tick < ticks:
            for _ in range(rng.randint(0, 2)):
                self.op(rng, ops)
            for _ in range(ticks_per_frame):
                App.g_kTimerManager._time += TICK_DELTA
                game_loop._update_ship_subsystems()
            for _ in range(rng.randint(0, 2)):
                self.op(rng, ops)
            for _ in range(ticks_per_frame):
                self.tick += 1
                ships = list(iter_ships())
                with host_loop._combat_effect_scope():
                    host_loop._advance_weapons(ships, TICK_DELTA)
                    host_loop._advance_combat(ships, TICK_DELTA,
                                              player=self.player,
                                              push_render_data=False)
                host_loop._combat_tick_boundary()   # as the host does (native damage)
                self.record()
                if rng.random() < 0.3:
                    self.op(rng, mid_ops)
            sensor_contacts.tick(self.player,
                                 App.g_kUtopiaModule.GetGameTime())
        self.audit = []
        if self.native:
            nc.audit_mirror()
            self.audit = list(nc.audit_failures())
            assert _h.combat_k1_depth() == 0
            assert not _h.combat_k0_open()
        self.counts = nc.counts()
        self.effects = effect_queue.counts()
        return self


# K0's inputs on top of the K1 fight (firing, so banks drain and deplete and
# tubes empty, while charges, power and slots are written around them).
K0_OPS = (("charge",) * 3 + ("odd_charge",) * 3 + ("recharge_all",)
          + ("drain",) * 3 + ("tractor_drain",) * 2 + ("tube_fire",) * 4
          + ("tube_dec",) * 3 + ("tube_set",) * 3 + ("sys_power",) * 2
          + ("phaser_level",) * 2 + ("worn",) * 2)
OPS = k1d.OPS + K0_OPS
# Between two ticks of a frame: no op that writes a tube's slots by hand (a
# fire from a loaded slot still happens, through K1), so Review Focus 4's
# "nothing credited after the first session" holds slot for slot.
MID_OPS = tuple(k for k in OPS if k not in (
    "reload", "player_torps", "tube_fire", "tube_dec", "tube_set"))


def _both(monkeypatch, ticks_per_frame, seed, ops=OPS, mid_ops=MID_OPS,
          ticks=TICKS):
    runs = []
    for env in (k1d.OFF, k1d.ON):
        with monkeypatch.context() as mp:
            mp.setattr(k1d, "SEED", seed)
            scene = _K0Scene(mp, env)
            runs.append(scene.run(ticks_per_frame, ops, mid_ops,
                                  ticks=ticks))
    ref, nat = runs
    _compare(ref, nat)
    return ref, nat


def _compare(ref, nat):
    # K1's record, every event, the presentation; fire control is native in
    # both arms (fire control native only, M9).
    k1d._compare(ref, nat)
    assert len(ref.k0_log) == len(nat.k0_log) == ref.tick
    for tick, ((now_a, a), (now_b, b)) in enumerate(
            zip(ref.k0_log, nat.k0_log), start=1):
        assert now_a.hex() == now_b.hex(), tick
        for x, y in zip(a, b):
            assert x == y, "tick %d differs:\n python %r\n native %r" % (
                tick, x, y)
    assert ref.k0_events == nat.k0_events
    for i, (x, y) in enumerate(zip(ref.k0_produced, nat.k0_produced)):
        assert x == y, "production %d differs:\n python %r\n native %r" % (
            i, x, y)
    assert len(ref.k0_produced) == len(nat.k0_produced)


def _check_native_ran(ref, nat, ticks=TICKS):
    """K0 ran every tick in the native arm (never in the reference), with
    each of its records, and the fight produced every event compared."""
    c = nat.counts
    check_weapon_state_paths(c)
    assert ref.counts["k0_steps"] == 0, ref.counts
    # Banks were stopped (depleted, or by the op stream) with their loops
    # playing, and those stops compared.
    assert effect_split.stops(ref.queued) > 0, ref.queued.rows[:20]
    assert c["k0_records"]["DONE"] == ticks, c["k0_records"]
    assert not any(c["k0_python_step_reasons"].values()), c
    # Every owned watcher's value equalled its row's `_watch_value`, every
    # tick (the old value K0's WATCH carries).
    assert nat.watch_checked >= ticks, nat.watch_checked
    assert nat.watch_mismatch == [], nat.watch_mismatch[:5]
    # K0 returns only RUN_PYTHON and DONE (combat fire events Task 4): the
    # stops, reloads and watcher lines are logged with their entries.
    for kind in ("DEPLETE_STOP", "RELOADED", "WATCH"):
        assert c["k0_records"][kind] == 0, (kind, c["k0_records"])
    logged, entries = c["k0_logged"], c["k0_entries"]
    for kind in ("deplete_stop", "reload", "watch"):
        assert logged[kind] > 0, (kind, logged)
    assert entries["TORPEDO_RELOAD"] == logged["reload"], c
    assert entries["WATCH"] == logged["watch"], c
    assert 0 < entries["LOOP_STOP"] <= logged["deplete_stop"], c
    # Every reload posted, both arms: each one K0's (no reload hand-back).
    reloads = sum(1 for e in ref.k0_events if e[0] == "reload")
    assert reloads == logged["reload"], (reloads, logged)
    kinds = {e[0] for e in ref.k0_events}
    assert kinds == {"reload", "charge_toggle", "fired"}, kinds
    assert {e[0] for e in ref.k0_produced} == {"fired"}, ref.k0_produced[:5]
    # Launches posted by ops (an op's StartFiring, a hand tube_fire) and by
    # the tick's step alike.
    assert {e[3] for e in ref.k0_produced} == {"op", "step"}, \
        ref.k0_produced[:5]
    # The native arm's were queued and delivered at the tick boundary; the
    # reference never opened the tick's scope, so its K0 producers acted at
    # once and it queued only the damage kinds (native damage M2: both
    # arms) and what K1's own sessions deferred (fire control is native in
    # both arms: fire control native only, M9).
    e = nat.effects
    assert e["delivered"] > e["damage"], e
    assert e["skipped_gone"] == e["failed"] == 0, e
    assert nat.scopes.opened > 0, nat.scopes.opened
    assert ref.scopes.opened == 0, ref.scopes.opened
    assert ref.effects["skipped_gone"] == ref.effects["failed"] == 0, \
        ref.effects
    # The odd charges were written, and kept ones reached the comparison.
    assert set(ref.odd) == {"nan", "-0.0", "0.0"}, ref.odd
    states = [s for _now, row in ref.k0_log for s in row]
    assert any(s[1] == ("float", "nan") for s in states)


@pytest.mark.parametrize("seed", (k1d.SEED, k1d.SEED + 7))
@pytest.mark.parametrize("ticks_per_frame", (1, 6))
def test_k0_matches_python_in_a_fight(monkeypatch, ticks_per_frame, seed):
    ref, nat = _both(monkeypatch, ticks_per_frame, seed)
    _check_native_ran(ref, nat)
    print("k0 differential (tpf=%d seed=%d): k0 %r logged %r entries %r "
          "reasons %r, c_applied %d, fast pushes %d, k0 events %d, "
          "launches posted %d"
          % (ticks_per_frame, seed,
             {k: v for k, v in nat.counts["k0_records"].items() if v},
             nat.counts["k0_logged"], nat.counts["k0_entries"],
             {k: v for k, v in nat.counts["k0_python_reasons"].items() if v},
             nat.counts["c_applied_writes"], nat.counts["fast_pushes"],
             len(ref.k0_events), len(ref.k0_produced)))


def _slot_rows(scene):
    """Per tick: (now, {tube index: (timers, advanced, same lists)})."""
    tubes = [i for i, w in enumerate(scene.weapons)
             if isinstance(w, ws.TorpedoTube)]
    return [(now, {i: (row[i][7], row[i][8], row[i][10]) for i in tubes})
            for now, row in scene.k0_log]


def test_three_sessions_a_frame_credit_once(monkeypatch):
    """Review Focus 4: three ticks a frame, so three K0 sessions back to
    back on ONE game clock. Each cooling slot is credited the whole frame
    in the first session (advanced to the frame's clock from the previous
    frame's) and nothing in the second and third, in both arms alike."""
    ref, nat = _both(monkeypatch, 3, k1d.SEED)
    _check_native_ran(ref, nat)
    loaded = ("float", ws._SLOT_LOADED.hex())
    credited = zero = 0
    for scene in (ref, nat):
        rows = _slot_rows(scene)
        for f in range(1, len(rows) // 3):
            t0, t1 = 3 * f - 1, 3 * f       # last of frame f-1, first of f
            now_prev, now = rows[t0][0], rows[t1][0]
            # One clock for the frame's three sessions.
            assert rows[t1 + 1][0] == now == rows[t1 + 2][0], f
            assert now > now_prev, f
            for i, (timers, adv, _same) in rows[t1][1].items():
                before = rows[t0][1][i]
                for s, (tm, at) in enumerate(zip(timers, adv)):
                    if tm == loaded or before[0][s] == loaded:
                        continue
                    if (before[1][s] == ("float", now_prev.hex())
                            and at == ("float", now.hex())
                            and float.fromhex(tm[1])
                            > float.fromhex(before[0][s][1])):
                        credited += 1
                # The second and third sessions: nothing credited.
                for t in (t1 + 1, t1 + 2):
                    timers_t, adv_t, same = rows[t][1][i]
                    prev_timers, prev_adv, _ = rows[t - 1][1][i]
                    for s, tm in enumerate(timers_t):
                        if tm == loaded or prev_timers[s] == loaded:
                            continue
                        assert adv_t[s] == ("float", now.hex()), (f, i, s)
                        assert tm == prev_timers[s], (f, t, i, s)
                        zero += 1
    assert credited > 0 and zero > 0, (credited, zero)
    print("three sessions a frame: %d first-session credits, %d zero "
          "credits after" % (credited, zero))
