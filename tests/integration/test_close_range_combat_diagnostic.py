"""Close-range combat diagnostic — no assertions, just a log dump.

The activation smokes proved every PlainAI body's Update() returns a
valid US_* integer. They explicitly deferred kinematic correctness
("does the ship maneuver right?") and weapon dispatch ("does it
actually fire?") to per-mission follow-on work.

Live-game observation (./build/dauntless OPEN_STBC_HOST_MISSION=
Custom.Tutorial.Episode.M3Gameflow.M3Gameflow): hostile ships fly
at their target, overlap geometry, and stop — and no phaser beams
or torpedoes ever appear. This test pits two Galaxy-like ships
200m apart, both NonFedAttack-AI'd at each other, ticks 60 frames,
and prints:

  * which PlainAI Update() ran each tick (the priority-list winner)
  * every motion setpoint write (SetSpeed/SetImpulse/turn solvers)
  * every weapon StartFiring / StopFiring call
  * per-tick firing state on each weapon system

Run with `-s` to see the table. This test has no assertions and is
NOT a CI gate; it's a sighting scope for shaping Slice G/H/I.
"""
import pytest

import App
from engine.appc import ai_driver
from engine.appc.ai_driver import tick_all_ai, US_ACTIVE
from engine.appc.ships import ShipClass
from engine.appc.subsystems import (
    HullSubsystem, PhaserSystem, TorpedoSystem, TorpedoAmmoType,
    PulseWeaponSystem, ImpulseEngineSubsystem, SensorSubsystem,
    ShieldSubsystem,
)
from engine.core.game import Game, Episode, Mission, _set_current_game


# ── Test fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def game_context():
    mission = Mission()
    mission.SetScript("tests.integration.test_close_range_combat_diagnostic")
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield
    _set_current_game(None)


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


# ── Combatant builder ────────────────────────────────────────────────────────

def _make_combatant(pSet, name: str, x: float, y: float, z: float) -> ShipClass:
    """Galaxy-ish ship with the subsystems NonFedAttack actually exercises.

    Mirrors test_non_fed_attack_smoke's stack + adds a ShieldSubsystem so the
    FwdShieldsLow ConditionalAI's condition can evaluate without crashing
    (its EvalFunc reads ConditionSingleShieldBelow which dereferences
    GetShields().GetCurShields(FRONT)). Pulse system populated so the
    FwdTorpsOrPulseReady's ConditionPulseReady condition has something
    to inspect.
    """
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)

    ies = ImpulseEngineSubsystem("IES"); ies.SetMaxSpeed(120.0)
    s._impulse_engine_subsystem = ies
    # NoSensorsEvasive ConditionalAI latches ACTIVE if no sensor subsystem;
    # without one the SelectTarget combat subtree is starved.
    s._sensor_subsystem = SensorSubsystem("Sensors")

    phaser = PhaserSystem("P"); phaser._parent_ship = s
    s._phaser_system = phaser
    torp = TorpedoSystem("T"); torp._parent_ship = s
    torp._ammo_by_slot = {0: TorpedoAmmoType("Photon", launch_speed=19.0)}
    s._torpedo_system = torp
    s._pulse_weapon_system = PulseWeaponSystem("PW")
    s._pulse_weapon_system._parent_ship = s

    # ShieldSubsystem with non-zero max so FwdShieldsLow's
    # GetCurShields/GetMaxShields don't divide-by-zero.
    shield = ShieldSubsystem("Shields")
    for face in range(6):
        shield.SetMaxShields(face, 100.0)
        shield.SetCurShields(face, 100.0)
    s._shield_subsystem = shield

    pSet.AddObjectToSet(s, name)
    return s


# ── Logging hooks ────────────────────────────────────────────────────────────

class CombatLog:
    """Single log of (tick, ship, event_type, detail) for both ships."""
    def __init__(self):
        self.entries: list[tuple] = []
        self.tick = 0

    def record(self, ship_name: str, kind: str, detail) -> None:
        self.entries.append((self.tick, ship_name, kind, detail))


def _install_hooks(log: CombatLog, ships: list[ShipClass]) -> list:
    """Monkey-patch instance methods on each ship + its weapon systems to
    record per-call diagnostic data. Returns a list of (obj, attr, orig)
    triples so the caller can restore on teardown.
    """
    restorers = []

    def _wrap(obj, attr, recorder):
        orig = getattr(obj, attr)

        def wrapper(*args, **kwargs):
            recorder(args, kwargs)
            return orig(*args, **kwargs)
        # Instance-level shadow over the bound class method.
        obj.__dict__[attr] = wrapper
        restorers.append((obj, attr, orig))

    for ship in ships:
        name = ship.GetName()

        def speed_rec(args, _kw, _n=name):
            speed = args[0] if args else None
            d = args[1] if len(args) > 1 else None
            dvec = (d.x, d.y, d.z) if d is not None else None
            log.record(_n, "SetSpeed", (speed, dvec))

        def impulse_rec(args, _kw, _n=name):
            speed = args[0] if args else None
            d = args[1] if len(args) > 1 else None
            dvec = (d.x, d.y, d.z) if d is not None else None
            log.record(_n, "SetImpulse", (speed, dvec))

        def turn_to_loc_rec(args, _kw, _n=name):
            v = args[0] if args else None
            vt = (v.x, v.y, v.z) if v is not None else None
            log.record(_n, "TurnTowardLocation", vt)

        def turn_dirs_rec(args, _kw, _n=name):
            pf = args[0] if len(args) > 0 else None
            pt = args[1] if len(args) > 1 else None
            pf_t = (pf.x, pf.y, pf.z) if pf is not None else None
            pt_t = (pt.x, pt.y, pt.z) if pt is not None else None
            log.record(_n, "TurnDirsToDirs", (pf_t, pt_t))

        def set_av_rec(args, _kw, _n=name):
            v = args[0] if args else None
            vt = (v.x, v.y, v.z) if v is not None else None
            log.record(_n, "SetTargetAV", vt)

        _wrap(ship, "SetSpeed", speed_rec)
        _wrap(ship, "SetImpulse", impulse_rec)
        _wrap(ship, "TurnTowardLocation", turn_to_loc_rec)
        _wrap(ship, "TurnDirectionsToDirections", turn_dirs_rec)
        _wrap(ship, "SetTargetAngularVelocityDirect", set_av_rec)

        # Weapon-system fire dispatch — what FireScript and StationaryAttack
        # both ultimately hit.
        phaser = ship.GetPhaserSystem()
        if phaser is not None:
            def ph_start(args, _kw, _n=name):
                target = args[0] if args else None
                tn = target.GetName() if target is not None and hasattr(target, "GetName") else repr(target)
                log.record(_n, "Phaser.StartFiring", tn)

            def ph_stop(args, _kw, _n=name):
                log.record(_n, "Phaser.StopFiring", None)
            _wrap(phaser, "StartFiring", ph_start)
            _wrap(phaser, "StopFiring", ph_stop)

        torp = ship.GetTorpedoSystem()
        if torp is not None:
            def t_start(args, _kw, _n=name):
                target = args[0] if args else None
                tn = target.GetName() if target is not None and hasattr(target, "GetName") else repr(target)
                log.record(_n, "Torp.StartFiring", tn)

            def t_stop(args, _kw, _n=name):
                log.record(_n, "Torp.StopFiring", None)
            _wrap(torp, "StartFiring", t_start)
            _wrap(torp, "StopFiring", t_stop)

    return restorers


def _install_plainai_logger(log: CombatLog):
    """Wrap ai_driver._tick_plain so we record which PlainAI's Update
    actually fires each tick (priority-list winner trail).

    A PlainAI is the leaf where motion+fire decisions land. By logging
    which leaf ran on which ship per tick we get the SDK priority gate
    trace without having to instrument every Conditional / PriorityList /
    Preprocessing node.
    """
    orig = ai_driver._tick_plain

    def wrapper(ai, game_time):
        # Mirror the gate inside _tick_plain so we only log Updates that
        # actually run (status ACTIVE + next_update_time reached).
        if ai._status == US_ACTIVE and game_time >= ai._next_update_time:
            inst = ai.GetScriptInstance()
            update_fn = getattr(inst, "Update", None) if inst is not None else None
            if callable(update_fn):
                ship = ai.GetShip()
                ship_name = ship.GetName() if ship is not None and hasattr(ship, "GetName") else "?"
                body = ai.GetScriptModule() or type(inst).__name__
                ai_name = ai.GetName() or "?"
                log.record(ship_name, "PlainAI.Update", f"{body}/{ai_name}")
        return orig(ai, game_time)

    ai_driver._tick_plain = wrapper
    return orig


def _restore_hooks(restorers, orig_tick_plain) -> None:
    for obj, attr, _orig in restorers:
        # Strip the instance shadow so the bound class method is back in
        # effect; do NOT reassign _orig since that was a bound method
        # captured at hook-install time.
        obj.__dict__.pop(attr, None)
    ai_driver._tick_plain = orig_tick_plain


# ── Per-tick observability ──────────────────────────────────────────────────

def _snapshot_firing_state(ship: ShipClass) -> dict:
    out = {}
    p = ship.GetPhaserSystem()
    if p is not None:
        out["phaser_on"] = bool(p.IsOn())
        out["phaser_fire_held"] = getattr(p, "_fire_held", False)
        out["phaser_firing_n"] = sum(
            1 for i in range(p.GetNumWeapons())
            if p.GetWeapon(i) is not None and p.GetWeapon(i).IsFiring())
    t = ship.GetTorpedoSystem()
    if t is not None:
        out["torp_on"] = bool(t.IsOn())
        out["torp_firing_n"] = sum(
            1 for i in range(t.GetNumWeapons())
            if t.GetWeapon(i) is not None and t.GetWeapon(i).IsFiring())
    return out


def _snapshot_position(ship: ShipClass) -> tuple:
    loc = ship.GetWorldLocation()
    return (round(loc.x, 1), round(loc.y, 1), round(loc.z, 1))


# ── The diagnostic test ──────────────────────────────────────────────────────

def test_close_range_combat_log(game_context, capsys):
    """Print a per-tick log of AI winners, setpoints, and firing state.

    No assertions — this is a sighting scope, not a gate.
    """
    pSet = App.SetClass_Create(); pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    # 200 m apart along +Y. Galaxy bounding-sphere is ~315 m, so the two
    # ships overlap at start — the prompt's "close range" scenario.
    attacker = _make_combatant(pSet, "Attacker", 0.0, 0.0, 0.0)
    target = _make_combatant(pSet, "Target", 0.0, 200.0, 0.0)

    import AI.Compound.NonFedAttack as non_fed_attack
    ai_a = non_fed_attack.CreateAI(attacker, "Target")
    ai_t = non_fed_attack.CreateAI(target, "Attacker")
    attacker.SetAI(ai_a)
    target.SetAI(ai_t)

    log = CombatLog()
    restorers = _install_hooks(log, [attacker, target])
    orig_tick_plain = _install_plainai_logger(log)

    try:
        # 60 ticks at the SDK's 60 Hz cadence (16.67 ms per tick).
        TICK_DT = 1.0 / 60.0
        snapshots: list[tuple] = []
        for i in range(60):
            log.tick = i
            tick_all_ai(game_time=i * TICK_DT)
            snapshots.append((
                i,
                _snapshot_position(attacker),
                _snapshot_position(target),
                _snapshot_firing_state(attacker),
                _snapshot_firing_state(target),
                attacker.GetSpeedSetpoint(),
                target.GetSpeedSetpoint(),
            ))
    finally:
        _restore_hooks(restorers, orig_tick_plain)

    # ── Report ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("CLOSE-RANGE COMBAT DIAGNOSTIC LOG")
    print("=" * 78)
    print(f"\nAttacker AI activated: {ai_a._activated} (err={ai_a._activation_error})")
    print(f"Target   AI activated: {ai_t._activated} (err={ai_t._activation_error})")

    print("\n--- Per-tick PlainAI winners ---")
    by_tick = {}
    for tick, ship, kind, detail in log.entries:
        if kind == "PlainAI.Update":
            by_tick.setdefault((tick, ship), []).append(detail)
    for i in range(60):
        a = by_tick.get((i, "Attacker"), [])
        t = by_tick.get((i, "Target"), [])
        if a or t:
            print(f"  tick {i:2d}: Attacker={a or '—'}   Target={t or '—'}")

    print("\n--- Setpoint writes (SetSpeed / SetImpulse / TurnTowardLocation / TurnDirsToDirs / SetTargetAV) ---")
    for tick, ship, kind, detail in log.entries:
        if kind in {"SetSpeed", "SetImpulse", "TurnTowardLocation",
                    "TurnDirsToDirs", "SetTargetAV"}:
            print(f"  tick {tick:2d} [{ship:8s}] {kind:18s} {detail}")

    print("\n--- Weapon fire dispatch ---")
    fire_events = [e for e in log.entries if e[2].startswith(("Phaser.", "Torp."))]
    if fire_events:
        for tick, ship, kind, detail in fire_events:
            print(f"  tick {tick:2d} [{ship:8s}] {kind:20s} {detail}")
    else:
        print("  (none — no StartFiring or StopFiring was called on either weapon system)")

    print("\n--- Periodic snapshots (positions, firing state, speed setpoint) ---")
    print(f"  {'tick':>4}  {'A_pos':>16}  {'T_pos':>16}  "
          f"{'A_phaser_on':>11}  {'A_fire_held':>11}  {'A_speed_sp':>10}  "
          f"{'T_phaser_on':>11}  {'T_fire_held':>11}  {'T_speed_sp':>10}")
    for i in (0, 5, 10, 20, 30, 45, 59):
        if i >= len(snapshots):
            continue
        _, ap, tp, afs, tfs, asp, tsp = snapshots[i]
        a_speed = f"{asp[0]:.2f}" if asp is not None else "—"
        t_speed = f"{tsp[0]:.2f}" if tsp is not None else "—"
        print(f"  {i:>4}  {str(ap):>16}  {str(tp):>16}  "
              f"{afs.get('phaser_on', '?')!s:>11}  {afs.get('phaser_fire_held', False)!s:>11}  {a_speed:>10}  "
              f"{tfs.get('phaser_on', '?')!s:>11}  {tfs.get('phaser_fire_held', False)!s:>11}  {t_speed:>10}")

    print("\n--- AI tree FireScript inspection ---")
    # Walk both AI trees and report each FireScript preprocessor's
    # bTargetVisible / iLastUpdate / sTarget state. This shows whether
    # the FireScript ever advanced past the "discover the target" gate.
    from engine.appc.ai import PreprocessingAI
    for ship_name, ai in (("Attacker", ai_a), ("Target", ai_t)):
        for node in ai.GetAllAIsInTree():
            if isinstance(node, PreprocessingAI):
                inst = node._preprocessing_instance
                if inst is not None and hasattr(inst, "lWeapons"):
                    print(f"  [{ship_name}] FireScript node={node.GetName()!r}  "
                          f"target={getattr(inst, 'sTarget', '?')!r}  "
                          f"bTargetVisible={getattr(inst, 'bTargetVisible', '?')}  "
                          f"iLastUpdate={getattr(inst, 'iLastUpdate', '?')}  "
                          f"len(lWeapons)={len(getattr(inst, 'lWeapons', []))}  "
                          f"bEnabled={getattr(inst, 'bEnabled', '?')}")
    print("=" * 78)
