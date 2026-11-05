"""Weapon subsystem hierarchy — split out of engine.appc.subsystems.

Holds the weapon classes (WeaponSystem and its descendants), the
_EnergyWeaponFireMixin, and the weapon-only module helpers. These are part
of engine.appc.subsystems' public surface and are re-exported from there, so
callers continue to ``from engine.appc.subsystems import PhaserSystem`` etc.

The base classes (ShipSubsystem, PoweredSubsystem) and the shared
subsystem-state/position predicates (_is_offline, subsystem_world_position)
stay in engine.appc.subsystems; we import them UP from there. Because of that
import direction, this module must never be imported before
engine.appc.subsystems has finished loading (the façade re-export at the
bottom of subsystems.py guarantees the normal load order).
"""

import math as _math

from engine.core import ids
from engine.appc import effect_queue, native_combat, passive_weapons
from engine.appc.native_combat import (
    NativeField, NativeFloatList, NativeRefField, NativeRefList,
    NativeSlotMap, NativeWakeField)
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.float_range_watcher import FloatRangeWatcher
from engine.appc.subsystems import (
    ShipSubsystem,
    PoweredSubsystem,
    _is_offline,
    subsystem_world_position,
)


# ── Voice priority (guide §8) ──────────────────────────────────────────────
# BC's shipped voice priorities (TGSound+0x68) -- a voice-stealing RANK, never
# a gain. 0.9 when the firing ship is the local player's; remote is
# per-weapon. Co-fired voices (phaser Start + Loop) take the second at
# priority - 0.01; the purpose of that step is unknown, and BC's consumer of
# the field was never identified, so treat all of this as best-reading, not
# gospel.
LOCAL_FIRE_PRIORITY = 0.9
REMOTE_PHASER_PRIORITY = 0.6
REMOTE_PULSE_PRIORITY = 0.5
CO_FIRED_PRIORITY_STEP = 0.01


# ── Torpedo reload slots ───────────────────────────────────────────────────
# BC stores one float per MaxReady at TorpedoTube+0xAC
# (docs/reference/gameplay/combat-and-damage.md:748).  We store the
# GAME TIME at which each slot began cooling; _SLOT_LOADED means "ready".
_SLOT_LOADED = -1.0


def _game_time() -> float:
    """The game clock — pause-frozen and frame-rate independent.

    NEVER time.monotonic(): wall time advances while the sim is frozen, which
    made every tube instantly reload on unpause.  Deferred import is the
    established idiom in this module (see spawn_launch).

    The import lives INSIDE the try: an ImportError here must fall through to
    the same 0.0 sentinel as any other clock failure, not escape uncaught.

    The 0.0 fallback is silent by design (a per-frame weapon loop must never
    raise), but silent-and-permanent is dangerous here: CanFire's gate
    (0 - 0 = 0 < ImmediateDelay) and UpdateReload's gate (0 - 0 = 0 <
    ReloadDelay) both stay false forever once every stamp is 0.0, bricking
    every torpedo tube with no exception anywhere. Route the swallow through
    dev_mode.log_swallowed (same idiom as _broadcast_reload below) so a
    developer can see it happened instead of just watching torpedoes stop
    reloading."""
    try:
        import App
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception as _e:
        from engine import dev_mode
        dev_mode.log_swallowed("torpedo tube _game_time clock read", _e)
        return 0.0


def _resolve_aim_world(ship, target):
    """Unit vector in world space from ship → target, or ship-forward if no target."""
    if (ship is not None and target is not None
            and hasattr(target, "GetWorldLocation")
            and hasattr(ship, "GetWorldLocation")):
        ship_pos   = ship.GetWorldLocation()
        target_pos = target.GetWorldLocation()
        dx = target_pos.x - ship_pos.x
        dy = target_pos.y - ship_pos.y
        dz = target_pos.z - ship_pos.z
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length > 1e-6:
            return TGPoint3(dx / length, dy / length, dz / length)
    # Fallback: ship's body +Y axis rotated into world.
    fwd = TGPoint3(0.0, 1.0, 0.0)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            fwd.MultMatrixLeft(rot)
    length = (fwd.x * fwd.x + fwd.y * fwd.y + fwd.z * fwd.z) ** 0.5
    if length > 1e-6:
        return TGPoint3(fwd.x / length, fwd.y / length, fwd.z / length)
    return TGPoint3(0.0, 1.0, 0.0)


def _resolve_bank_aim_world(bank, target):
    """Unit vector from a bank's mount Position (world) → target.

    The firing arc originates at the bank's mount point on the ship's
    hull, NOT at the ship's centre of mass and NOT at the strip emit
    point.  Galaxy DorsalPhaser1's Position = (0, 1.27, 0.5) sits a
    full GU forward of ship centre; at close range the two aims
    disagree by tens of degrees, causing arcs to gate inconsistently
    between the fire-time check and the per-tick re-check.  See
    research doc § "Bug F".

    Falls back to ship-pos based aim when the bank has no parent ship
    (legacy fixtures, unit tests).
    """
    if bank is None or target is None or not hasattr(target, "GetWorldLocation"):
        return _resolve_aim_world(None, target)
    if not hasattr(bank, "_emitter_world_position"):
        ship = bank._climb_to_ship() if hasattr(bank, "_climb_to_ship") else None
        return _resolve_aim_world(ship, target)
    origin = bank._emitter_world_position()
    target_pos = target.GetWorldLocation()
    dx = target_pos.x - origin.x
    dy = target_pos.y - origin.y
    dz = target_pos.z - origin.z
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length > 1e-6:
        return TGPoint3(dx / length, dy / length, dz / length)
    # Degenerate: bank Position coincides with target — fall back to
    # ship-forward so the arc gate has a sensible direction to test.
    ship = bank._climb_to_ship() if hasattr(bank, "_climb_to_ship") else None
    return _resolve_aim_world(ship, None)


def _emitter_world_direction(emitter, ship) -> TGPoint3:
    """The emitter's mount direction rotated into WORLD space.

    This is what BC's Weapon::CalculateRoughDirection returns.  Evidence:
    AI/Preprocessors.py:447-456 dots the result against a world-space target
    delta, and AI/PlainAI/IntelligentCircleObject.py:204,234 converts it
    world->model explicitly ("Change it to model space").

    DISTINCT from GetDirection(), which stays MODEL space — ConditionTorpsReady
    .py:128 dots that against a model-space restriction vector.  Do not conflate.

    Orphaned emitter (no owning ship): return the un-rotated body direction.

    Guards on hasattr, not isinstance(emitter, ShipSubsystem): _emitter_in_arc
    reuses this helper with duck-typed test doubles (see
    tests/unit/test_property_set_orientation.py::_FakeEmitter) that implement
    GetDirection() without subclassing ShipSubsystem.
    """
    local = emitter.GetDirection() if hasattr(emitter, "GetDirection") else None
    if not isinstance(local, TGPoint3):
        local = TGPoint3(0.0, 1.0, 0.0)     # BC model-forward default
    world = TGPoint3(local.x, local.y, local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world.MultMatrixLeft(rot)       # v_world = R . v_body (column-vector)
    return world


def _emitter_in_arc(emitter, ship, aim_world):
    """Returns True if `aim_world` (unit vector) lies inside the emitter's
    firing arc, rotated into world space via the ship's rotation.

    Emitters with explicit SetArcWidthAngles / SetArcHeightAngles use a
    yaw × pitch rectangular cone.  Bare emitters (no arc setters — i.e.
    torpedo tubes) fall back to a 90° dot-product check against the
    emitter's SetDirection.
    """
    if not hasattr(emitter, "GetDirection"):
        return True
    try:
        local_dir = emitter.GetDirection()
    except Exception:
        return True
    if not isinstance(local_dir, TGPoint3):
        return True
    world_dir = _emitter_world_direction(emitter, ship)

    # Emitter without explicit arc bounds (torpedo tubes) — fall back to
    # a 90° dot-product cone.  ShipSubsystem always exposes a typed
    # GetArcWidthAngles() returning wide defaults, so the trigger for the
    # arc check is the _arc_set flag set by SetProperty when an
    # EnergyWeaponProperty actually supplied bounds.  Bare test emitters
    # (no _arc_set attr at all) use the same typed-tuple probe as before.
    use_arc_check = getattr(emitter, "_arc_set", None)
    if use_arc_check is None:
        arc_w = None
        if hasattr(emitter, "GetArcWidthAngles"):
            try:
                arc_w = emitter.GetArcWidthAngles()
            except Exception:
                arc_w = None
        use_arc_check = isinstance(arc_w, tuple) and len(arc_w) == 2
    if not use_arc_check:
        return (world_dir.x * aim_world.x
              + world_dir.y * aim_world.y
              + world_dir.z * aim_world.z) > 0.0
    arc_w = emitter.GetArcWidthAngles()

    # Up: rotate the stored body up axis directly into world space.
    up_local = emitter.GetUp() if hasattr(emitter, "GetUp") else TGPoint3(0.0, 0.0, 1.0)
    world_up = TGPoint3(up_local.x, up_local.y, up_local.z)
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        rot = ship.GetWorldRotation()
        if isinstance(rot, TGMatrix3):
            world_up.MultMatrixLeft(rot)

    # Right = world_forward × world_up. Under the right-handed convention
    # (post 2026-06-18 un-mirror: AlignToVectors builds forward × up, det > 0,
    # and the renderer draws R with no reflection) this equals R·(forward×up)
    # = R·GetCol(0) = the TRUE starboard axis the player sees. Deriving it as a
    # cross of the rotated forward/up keeps gate and beam in one frame and is
    # handedness-correct without reading the stored _right. Matches
    # _strip_emit_position. See tests/unit/test_phaser_arc_handedness.py and
    # docs/superpowers/plans/2026-06-18-render-handedness-unmirror.md.
    world_right = TGPoint3(
        world_dir.y * world_up.z - world_dir.z * world_up.y,
        world_dir.z * world_up.x - world_dir.x * world_up.z,
        world_dir.x * world_up.y - world_dir.y * world_up.x,
    )

    # Project aim onto body frame.
    fwd_dot   = world_dir.x   * aim_world.x + world_dir.y   * aim_world.y + world_dir.z   * aim_world.z
    right_dot = world_right.x * aim_world.x + world_right.y * aim_world.y + world_right.z * aim_world.z
    up_dot    = world_up.x    * aim_world.x + world_up.y    * aim_world.y + world_up.z    * aim_world.z

    import math as _math
    yaw   = _math.atan2(right_dot, fwd_dot)
    pitch = _math.asin(max(-1.0, min(1.0, up_dot)))

    # Bounds are an unordered pair. Stock hardpoints author some larger-first
    # -- every Fed Starbase phaser, the Ambassador/Akira/Cardassian-station
    # belly phasers (cardstarbase.py: SetArcHeightAngles(1.745329, -0.087266))
    # -- and read literally that range is empty, so the bank never fires.
    # The getters keep the authored order; only the gate sorts.
    yaw_lo, yaw_hi = sorted(arc_w)
    arc_h = emitter.GetArcHeightAngles() if hasattr(emitter, "GetArcHeightAngles") else None
    if not (isinstance(arc_h, tuple) and len(arc_h) == 2):
        # Arc width set but height missing — allow any pitch.
        return yaw_lo <= yaw <= yaw_hi
    pitch_lo, pitch_hi = sorted(arc_h)
    return (yaw_lo <= yaw <= yaw_hi) and (pitch_lo <= pitch <= pitch_hi)


# ── Discharge sources (RE'd from stbc.exe 2026-09-14; experiment doc
# 2026-09-09-phaser-discharge-rate-source.md, Findings Q-D1..Q-D5) ────────
#
# Three energy-weapon subclasses, three consumption models.  There is NO
# shared base-class discharge — the common UpdateCharge has a recharge arm
# only — so the property the hardpoint authors as `NormalDischargeRate` is
# read by exactly one gameplay path (pulse) and ignored by the other (phaser).
#
# PhaserBank: charge-units per SECOND while the beam is up, indexed by the
# owning PhaserSystem's power level (system field, not the bank's).  It is
# the sibling of the power-level DAMAGE table (0.25/0.5/0.5 at 0x00893170):
# same index, contiguous, at 0x0089317c..0x00893184.  Not scaled by bank
# condition (recharge is; discharge is not).
PHASER_DISCHARGE_BY_POWER_LEVEL = (0.35, 1.0, 1.0)      # PP_LOW, PP_MEDIUM, PP_HIGH

# PulseWeapon: a flat per-SHOT cost, taken inside Fire, of the authored
# NormalDischargeRate × this scale on the weapon's OWN PowerSetting
# (EnergyWeapon field — a different field from PhaserSystem.PowerLevel;
# collapsing the two is the next bug of this shape).
PULSE_COST_SCALE_BY_POWER_SETTING = (0.5, 1.0, 2.0)     # LOW, MED, HIGH
# PulseWeapon::GetDamageScale (0x00575270): a pure function of the same
# power setting — a bolt lands as the projectile script's GetDamage() × this.
# Read from the exe and measured on seven hulls (clean-room
# PulseWeaponDamage.md C1–C7; stbc-oracle `pulse_warbird_front_40_{low,meta,
# high}`): Warbird RomulanCannon 400 → 80 / 200 / 400; the setting is 1 on
# every stock emitter, so every stock bolt lands at HALF its script value —
# the Bird of Prey's apparent 220 is two 110-bolts in one sample. Damage and
# cost move together, which is why a full charge buys the same burst total
# at any setting. Nothing in any hardpoint, ship or projectile script sets
# the power setting; only the scripted SetPowerSetting (and save-load) can.
PULSE_DAMAGE_SCALE_BY_POWER_SETTING = (0.2, 0.5, 1.0)   # LOW, MED, HIGH

# Beam timing, measured on the original exe (stbc-oracle bible §2.2 and the
# per-bank rows of `phaser_high_front_57` / `phaser_galaxy_front_57`):
#
#   * A bank that has just lit (IsFiring true) neither drains nor damages for
#     BEAM_ON_DELAY_S — two fire-timer thresholds (40 ticks). Its charge then
#     drains at the discharge rate and its dwell accumulates.
#   * Damage is not continuous: it is flushed as one pulse each time the
#     dwell exceeds BEAM_DWELL_FLUSH_S (the clean-room `0x00572440` step 6
#     threshold at `0x008E53E0`), the pulse being MaxDamage × intensity ×
#     distance factor × dwell. Measured: the first quantum lands 1.156 s
#     after IsFiring (= 0.656 + 0.5), then every 0.53 s; a Kessok beam's
#     quantum is 106.25 = 400 × 0.5 × 0.53125; a Galaxy bank's 66.4.
#   * The total a full charge delivers is the drain window minus the delay:
#     four Kessok beams, 7 charge at 1.0/s → 800/s × (7.5 − 0.66) s ≈ 5 470.
#
# The threshold is tested against the dwell banked BEFORE this frame, and the
# flush includes this frame's dt, so a pulse carries 32 ticks of dwell
# (0.533 at 60 Hz, quantum 106.7) — what the rows show — not 31.
BEAM_ON_DELAY_S = 2 * 0.33
# BC's inter-shot delay threshold (TryFireWeapon, 0x00584E40): a held
# weapon's fire timer must reach it before the walk tries it again. Pushed to
# the native K1 kernel (fire control's one copy, native_combat.push_globals).
FIRE_TIMER_THRESHOLD = 0.33
BEAM_DWELL_FLUSH_S = 0.5

# Default PowerSetting.  ASSUMED, not RE'd: the SDK never calls
# EnergyWeapon.SetPowerSetting (zero call sites) and the constructor value
# was not read from the image.  MED (×1.0) is the neutral choice — change it
# here and in test_energy_weapon_discharge_source.py together.
_DEFAULT_POWER_SETTING = 1


def _init_energy_weapon_state(self):
    """Shared init for PhaserBank/PulseWeapon/TractorBeam runtime state.

    Field names mirror EnergyWeaponProperty.  Pass 4 copies the property
    values onto these attributes after instantiation; until then they're
    all zero.
    """
    self._max_charge: float = 0.0
    self._min_firing_charge: float = 0.0
    self._normal_discharge_rate: float = 0.0
    self._recharge_rate: float = 0.0
    self._charge_level: float = 0.0
    self._power_setting: int = _DEFAULT_POWER_SETTING
    # Looped SFX handle started by Fire(), stopped by StopFiring().
    self._loop_handle = None
    # Beam-on countdown and damage dwell — see BEAM_ON_DELAY_S and
    # BEAM_DWELL_FLUSH_S. Both game-time. Pulse cannons never use them.
    self._beam_on_countdown: float = 0.0
    self._dwell: float = 0.0
    # Set when a beam runs dry; a depleted bank does not restart until its
    # charge is back to MinFiringCharge (native fire control's charge gate,
    # native/src/combat/src/fire_gates.cc).
    self._depleted: bool = False


def _resolve_fire_sound(prop) -> str:
    """Returns the FireSound name (typed accessor) or empty string."""
    if prop is None or not hasattr(prop, "GetFireSound"):
        return ""
    return prop.GetFireSound() or ""


# Keys already announced by _announce_once. Per process, never reset on a
# mission swap: the point is to tell the player once, not once per mission.
_announced: set = set()


def _announce_once(key, message: str) -> None:
    """Print a `[weapons]` line the first time `key` is seen.

    For weapons a sideloaded mod left without a projectile module or a fire
    sound -- usually because it depends on a pack the player never
    installed. Production output, not --developer only: otherwise the player
    sees a dead or mute weapon and nothing says why."""
    if key in _announced:
        return
    _announced.add(key)
    print("[weapons] " + message, flush=True)


# The substitute when a hardpoint's projectile module cannot be imported.
# BC's own baseline round, and already the ammo layer's fallback: when
# ships.py:_resolve_torpedo_ammo fails the same import it reports the type as
# "Photon" with photon launch speed and power cost. Completing that here keeps
# one story rather than a type calling itself Photon and firing nothing.
_FALLBACK_PROJECTILE = "Tactical.Projectiles.PhotonTorpedo"

# script name -> resolved module, or None once the fallback has also failed.
# Also the once-per-script log gate: an unimportable module is unimportable
# every shot, and a tube fires many times a minute.
_projectile_modules: dict = {}


def _resolve_projectile_module(script_name):
    """The SDK module for `script_name`, falling back to the stock photon.

    Community ship mods can ship projectile modules as Python 1.5 `.pyc`
    with NO source — the LC Intrepid pack's ZZ_VoyPhoton and ZZ_Tricobalt
    are magic 0x4E99, the Python `stbc.exe` embeds. Those now load: both SDK
    finders take a mod `.pyc` and engine/py15 lifts straight-line 1.5
    bytecode into the AST its source would have parsed to. What still lands
    here is bytecode the lifter refuses (it prints one `[sdk-loader]` line
    naming the module) or any other import failure.

    Substituting a photon is a DELIBERATE INFIDELITY, chosen so a sideloaded
    ship is flyable: a mod's tricobalt becomes an ordinary photon rather than
    nothing at all. It is not a reconstruction of anything BC does. Before
    this, the caller returned in silence AFTER Fire() had already spent the
    round and reloaded the tube, so a mod's torpedoes drained the magazine
    and launched nothing, with no event and no log.

    Returns None only when the fallback itself cannot be imported, which
    means the SDK tree is missing — the caller still declines to fire.
    """
    if script_name in _projectile_modules:
        return _projectile_modules[script_name]

    import importlib
    from engine import dev_mode
    try:
        mod = importlib.import_module(script_name)
    except Exception as _e:
        # Not just ImportError: a Python-2-era module can also raise
        # SyntaxError or AttributeError through the SDK loader's fixups, and
        # every one of those leaves us equally unable to launch.
        dev_mode.log_swallowed(
            "projectile module %r unimportable; substituting %s"
            % (script_name, _FALLBACK_PROJECTILE), _e)
        _announce_once(("projectile", script_name),
                       "torpedo module %s not loadable -- firing %s instead"
                       % (script_name, _FALLBACK_PROJECTILE))
        try:
            mod = importlib.import_module(_FALLBACK_PROJECTILE)
        except Exception as _e2:
            dev_mode.log_swallowed(
                "fallback projectile %s unimportable" % _FALLBACK_PROJECTILE,
                _e2)
            mod = None

    _projectile_modules[script_name] = mod
    return mod


def _reset_projectile_module_cache() -> None:
    """Drop the resolved-module cache. Mission swaps reload the SDK tree and a
    mod install can change what resolves, so a cached failure must not outlive
    either."""
    _projectile_modules.clear()
    _pulse_params_cache.clear()
    _pulse_modules.clear()
    _tube_launch_cache.clear()
    # Not re-resolved here (mid mission-swap teardown): banks and ammo types
    # already built re-read their module on the next native push or K1 entry.
    native_combat.mark_pulse_stale()


# script name -> (module_ok, launch_speed, lifetime) for the native mirror
# (ruling P6). Cleared with _projectile_modules.
_pulse_params_cache: dict = {}

# script name -> the module those params were read from (module_ok 1 only):
# the module a cannon's native launch carries (native_combat.
# push_pulse_params; launch deferral, Task 3). Every K1 entry checks each
# entry against sys.modules and re-pushes a re-imported one
# (native_combat._refresh_stale_launches; fire control native only, M8.3).
_pulse_modules: dict = {}

# script name -> (launch state, launch speed) of a torpedo script, the per-
# type launch cache K1's native tube launch reads (P6 extended to tubes;
# spec 2026-11-02-combat-launch-deferral §4.1): read when an ammo type of the
# script is loaded (native_combat.push_ammo_launch), and pushed to every
# ammo type of that script. Cleared with _projectile_modules.
_tube_launch_cache: dict = {}

# The launch states (mirror.h ammo_launch_state).
LAUNCH_UNCACHED, LAUNCH_CACHED, LAUNCH_UNRESOLVED = range(3)


def tube_launch_params(mod) -> tuple:
    """(state, launch speed) of a resolved torpedo module: LAUNCH_UNRESOLVED
    for None (no module: the launch does not fire), else LAUNCH_CACHED
    and the speed the kernel's launch uses (GetLaunchSpeed(), 0.0 without
    one). What its Create does decides nothing: every launch inside the
    deferral runs it at the boundary (rulings L1, L6). A GetLaunchSpeed that
    raises stays uncached: its launches do not fire (a counted no-fire,
    launch_uncached)."""
    if mod is None:
        return (LAUNCH_UNRESOLVED, 0.0)
    try:
        speed = (float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed")
                 else 0.0)
    except Exception:       # noqa: BLE001 - uncached: a no-fire
        return (LAUNCH_UNCACHED, 0.0)
    return (LAUNCH_CACHED, speed)


def pulse_module_script(bank) -> str:
    """The projectile script PulseWeapon.Fire would import for `bank`: its
    property's GetModuleName(), or "" (Fire then refuses). Read from the
    instance dict, so it is safe while the bank is still being constructed."""
    prop = bank.__dict__.get("_property")
    script = prop.GetModuleName() if (
        prop is not None and hasattr(prop, "GetModuleName")) else ""
    return script or ""


def pulse_module_params(script) -> tuple:
    """(module_ok, launch_speed, lifetime) for the pulse projectile `script`,
    the values native fire control's pulse decision and launch direction
    read (pushed to the cannon's row; missing GetLaunchSpeed reads 0.0,
    missing GetLifetime the 8 s default). module_ok is 0 when the script is
    empty or does not import: that cannon does not fire (k1_no_fire
    pulse_module). Cached once per script, with the module itself
    (_pulse_modules)."""
    hit = _pulse_params_cache.get(script)
    if hit is None:
        mod, hit = _resolve_pulse_module(script)
        _pulse_params_cache[script] = hit
        if mod is not None:
            _pulse_modules[script] = mod
    return hit


def pulse_module(script):
    """The module `script`'s cached params were read from
    (pulse_module_params), or None (not resolved, or not importable)."""
    return _pulse_modules.get(script)


def resolve_pulse_module_params(script) -> tuple:
    """pulse_module_params without the cache (the audit's independent answer)."""
    return _resolve_pulse_module(script)[1]


def _resolve_pulse_module(script) -> tuple:
    """(the module or None, (module_ok, launch_speed, lifetime)) for
    `script`, imported as the cannon's decision imported it."""
    hit = (0, 0.0, 0.0)
    mod = None
    if script:
        import importlib
        from engine import dev_mode
        try:
            mod = importlib.import_module(script)
            speed = (float(mod.GetLaunchSpeed())
                     if hasattr(mod, "GetLaunchSpeed") else 0.0)
            life = (float(mod.GetLifetime()) if hasattr(mod, "GetLifetime")
                    else _PULSE_DEFAULT_LIFETIME)
            hit = (1, speed, life)
        except Exception as _e:  # noqa: BLE001 - announced, a no-fire
            mod = None
            dev_mode.log_swallowed(
                "pulse module %r not resolvable for the native mirror"
                % (script,), _e)
            # No fallback bolt (unlike torpedoes): the cannon stays dead
            # (module_ok 0: its Fire is a counted no-fire, fire control
            # native only, M6), but it says why instead of just never
            # firing -- the line the deleted Python decision printed.
            _announce_once(("projectile", script),
                           "pulse module %s not loadable -- those cannons "
                           "will not fire" % script)
    return mod, hit


# BC's range gate on the pulse launch solve: refuse when the predicted
# intercept is further than this many seconds' worth of effective bolt speed.
_PULSE_RANGE_GATE_SECONDS = 30.0
_PULSE_DEFAULT_LIFETIME = 8.0        # C++ default when the module has no GetLifetime


def _new_projectile(mod, source_ship, x, y, z):
    """The shared spawn's first half (the SPAWN delivery, spawn_launch): a
    Torpedo from `source_ship` at (x, y, z),
    then the module's Create (at the boundary for a deferred launch, whatever
    it does: rulings L1, L6)."""
    from engine.appc.projectiles import Torpedo

    torp = Torpedo()
    torp._source_ship = source_ship
    torp.SetTranslateXYZ(x, y, z)

    mod.Create(torp)
    return torp


def _launch_projectile(torp, mod, drf_override, velocity, target, offset,
                       kset):
    """The shared spawn's second half, with the fire-time values given:
    the launcher's DRF override (> 0), the launch velocity (None: the
    direction had no length, the torpedo keeps its own), the homing target
    (alive at fire time, else None) and its offset (a TGPoint3 copy or
    None); then register (joining `kset`: projectiles.LIVE_SET reads the
    source's set now) -- ET_TORPEDO_ENTERED_SET -- and the launch sound."""
    from engine.appc import projectiles

    # §3.2 DRF override: if the launching tube has a non-zero
    # DamageRadiusFactor (set by the hardpoint script, e.g.
    # galaxy.py ForwardTorpedo1.SetDamageRadiusFactor(0.20)),
    # it overrides the payload value set by mod.Create above.
    # host_loop passes the torpedo as hardpoint_weapon to apply_hit,
    # so torp._damage_radius_factor must carry the launcher value.
    if drf_override > 0.0:
        torp._damage_radius_factor = drf_override

    if velocity is not None:
        torp._velocity = velocity

    if target is not None:
        torp._target_ship = target
        torp._set_launch_offset(offset)
    else:
        torp._target_ship = None

    projectiles.register(torp, kset)
    _play_launch_sound(mod, torp)


def _play_launch_sound(mod, torp) -> None:
    """mod.GetLaunchSound(), attached to the torpedo's node and played."""
    from engine.audio.tg_sound import TGSoundManager

    if hasattr(mod, "GetLaunchSound"):
        sound_name = mod.GetLaunchSound()
        if sound_name:
            # BC (sdk/Build/scripts/MissionLib.py:3284-3296, verbatim):
            #   pSound = App.g_kSoundManager.GetSound(pcLaunchSound)
            #   if pSound != None:
            #       pSound.AttachToNode(pTorp.GetNode())
            #       pSoundRegion = App.TGSoundRegion_GetRegion(pSet.GetName())
            #       if pSoundRegion != None: pSoundRegion.AddSound(pSound)
            #       pSound.Play()
            #
            # PlaySound(name) (the old call here) passes no node and no
            # position; the sound is registered LS_3D (positional=True), and
            # the backend ORs that load-time flag in regardless of whether a
            # position was supplied -- so every launch played positional at
            # the world origin, untracked (no falloff, no doppler). Mirror
            # BC's GetSound -> AttachToNode -> Play sequence instead: torp is
            # its own node source (Torpedo.GetNode/GetWorldLocation, added
            # alongside this fix) so AttachToNode + attached_sources.pump
            # rides it through the whole flight, same as a ship's engine hum.
            #
            # Region association: BC's TGSoundRegion.AddSound scopes the
            # sound to the current set so a scene change can stop it in bulk.
            # TGSound.Play() already does the Dauntless-native equivalent
            # unconditionally once a node/position is present (see
            # engine.audio.scene_scope.register, called from Play() itself)
            # -- there is no separate set/region lookup cheaply reachable
            # from this call site, and none is needed: Play() covers it.
            snd = TGSoundManager.instance().GetSound(sound_name)
            if snd is not None:
                # Torpedo.GetNode() always returns a real (weak) node -- no
                # hasattr guard needed here (that would be the vacuous-True
                # TGObject.__getattr__ stub trap; GetNode is a real method on
                # Torpedo, not a stub). Prefer no attachment over a wrong
                # one: only Play() once a node is in hand, so a future
                # projectile type that can't supply one never falls back to
                # PlaySound's origin-pin bug.
                node = torp.GetNode()
                if node is not None:
                    snd.AttachToNode(node)
                    snd.Play()


def spawn_launch(launcher, kind, ship, kset, mod, target, record):
    """The SPAWN entry's delivery (effect_queue._spawn; spec 2026-11-02-
    combat-launch-deferral §4.1): K1 decided a launch and computed its fire-
    time values -- `record` is (position xyz, has velocity, velocity xyz,
    has offset, offset xyz, drf override, damage scale, fired at) -- so the
    torpedo is built now, at the boundary (_new_projectile,
    _launch_projectile) with those values for its live reads. `mod` is the
    module resolved when the launch was decided (the ammo type's cached one,
    or the cannon's, held from fire time). A tube's launch (kind 0, a dumb
    one 2) then posts its ET_TORPEDO_FIRED after the spawn.
    Returns the torpedo."""
    from engine.appc.math import TGPoint3

    (px, py, pz, has_velocity, vx, vy, vz, has_offset, ox, oy, oz,
     drf, damage_scale, fired_at) = record
    if mod is None:
        raise RuntimeError("combat SPAWN: no module (a launch is deferred "
                           "only with its module resolved)")
    torp = _new_projectile(mod, ship, px, py, pz)
    velocity = TGPoint3(vx, vy, vz) if has_velocity else None
    offset = None
    if target is not None and has_offset:
        offset = TGPoint3(ox, oy, oz)
    _launch_projectile(torp, mod, drf, velocity, target, offset, kset)
    if int(kind) == SPAWN_PULSE:
        # A cannon shot's tail, after the bolt exists: its damage
        # scaled AFTER register (its set-entry handlers saw the module's:
        # today's order, kept), then the shot's ET_WEAPON_FIRED (M4).
        torp._damage = float(torp._damage) * damage_scale
        _post_weapon_fired(launcher, fired_at)
    else:
        launcher._broadcast_torpedo_fired(torp)
    return torp


# K1Spawn::Kind (k1_fire_control.h): a SPAWN entry's kind operand.
SPAWN_TUBE, SPAWN_PULSE, SPAWN_DUMB = range(3)

# The weapons inside Weapon.FireDumb's Fire (innermost last): their launch
# is the dumb kind.


def _post_weapon_fired(weapon, target) -> None:
    """Post ET_WEAPON_FIRED, a TGObjPtrEvent: Source = the firing weapon,
    Destination = the owning ship (resolved via ``_climb_to_ship``), object
    pointer = the target the shot went at (None for a dumbfire) -- the SDK's
    WeaponFired handlers (E1M2, E2M1) ShipClass_Cast it and return when it
    is None.
    Shared by TorpedoTube.Fire (posted AFTER ET_TORPEDO_FIRED -- see
    TorpedoTube._broadcast_weapon_fired), PhaserBank.Fire (posted on the
    was-not-firing edge, Task 10, audited §1.6/§6) and PulseWeapon's shot
    (one per bolt) -- the SDK surface for the event bounds it to (weapon,
    owner ship) regardless of weapon type. Inside the effect queue's scope
    it is queued (WEAPON_FIRED) and posted at the tick boundary."""
    if effect_queue.deferring():
        effect_queue.post(effect_queue.WEAPON_FIRED, weapon, target)
        return
    import App
    from engine import dev_mode
    try:
        evt = App.TGObjPtrEvent_Create()
        evt.SetEventType(App.ET_WEAPON_FIRED)
        evt.SetSource(weapon)
        evt.SetDestination(weapon._climb_to_ship())
        evt.SetObjPtr(target)
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        dev_mode.log_swallowed("ET_WEAPON_FIRED broadcast", _e)


class _EnergyWeaponFireMixin:
    """Shared Fire/CanFire/StopFiring/UpdateCharge for PhaserBank / PulseWeapon
    / TractorBeam.  Per-emitter state initialised by _init_energy_weapon_state.
    Each class also has _firing (False at init), _target/_target_offset (None).

    SFX trigger looks up the property's FireSound name and asks TGSoundManager
    to play it.  Tries "<name> Start" first (phaser convention), falls back to
    bare "<name>" (tractor convention).  Names map to WAV assets via
    sdk/Build/scripts/LoadTacticalSounds.py invoked at audio init.
    """

    # Remote-fire voice priority. Default covers pulse + tractor (0.5);
    # PhaserBank overrides to 0.6. See the guide §8 constants above.
    REMOTE_FIRE_PRIORITY = REMOTE_PULSE_PRIORITY

    # ── Passive state (engine/appc/passive_weapons.py) ──────────────────────
    # The three fields UpdateCharge's idle early-out reads. A full idle bank
    # sleeps out of the weapons walk; any write to one of these (Fire,
    # SetChargeLevel, a property copy, a drain) wakes it. Reads stay plain
    # instance-dict reads: WakeField has no __get__.
    #
    # Mirrored into the native combat row on every write (native_combat): the
    # push comes after the wake, so nothing about waking changes.
    _charge_level = NativeWakeField(float)
    _firing = NativeWakeField(bool)
    _max_charge = NativeWakeField(float)
    _min_firing_charge = NativeField(float)
    _depleted = NativeField(bool)
    _normal_discharge_rate = NativeField(float)
    _power_setting = NativeField(int)
    # K2 reads the beam-on countdown (UpdateCharge counts it down every tick)
    # and the damage dwell.
    _beam_on_countdown = NativeField(float)
    _dwell = NativeField(float)
    # K0 (the charging kernel) reads the recharge rate.
    _recharge_rate = NativeField(float)

    def _passive_at_rest(self) -> bool:
        """True when UpdateCharge, run now, would return at its idle
        early-out -- the same test, on the same fields. TractorBeam's
        override reaches the same early-out when not firing (it only adds a
        firing branch), so the rule holds for it too."""
        return not self._firing and self._max_charge - self._charge_level <= 0.0

    def _passive_on_sleep(self) -> None:
        passive_weapons.on_sleep(self)

    def _passive_on_wake(self) -> None:
        passive_weapons.on_wake(self)

    # ── Weapon AI surface ────────────────────────────────────────────────────
    # BC's PhaserBank / PulseWeapon / TractorBeam ARE Weapons; ours derive from
    # WeaponSystem, so Weapon's two AI queries never reached them and fell
    # through to a truthy _Stub. IntelligentCircleObject.py:234-238 then dotted
    # the stub to 0 on every axis and filed every bank as pointing starboard,
    # and PhaserSweep.py:182 compared a stub against its arc threshold.
    # Same semantics as Weapon's versions (see Weapon.CalculateRoughDirection).

    def CalculateRoughDirection(self) -> TGPoint3:
        """WORLD-space mount direction, as Weapon.CalculateRoughDirection."""
        return _emitter_world_direction(self, self._climb_to_ship())

    def CalculateWeaponAppeal(self) -> float:
        """Weapon.CalculateWeaponAppeal's approximation: 1.0 functional, 0.0
        disabled. BC's formula is not recoverable from the SDK."""
        return 0.0 if self.IsDisabled() else 1.0

    def _remote_fire_priority(self) -> float:
        return self.REMOTE_FIRE_PRIORITY

    def _is_local_player_ship(self) -> bool:
        """True when the firing ship is the local player's (guide §8: 0.9).

        Same reach-for-the-player pattern as engine/appc/hit_feedback.py:246 --
        do not invent a second one.
        """
        parent_sys = self.GetParentSubsystem() if hasattr(self, "GetParentSubsystem") else None
        ship = parent_sys.GetParentShip() if parent_sys is not None and hasattr(parent_sys, "GetParentShip") else None
        if ship is None:
            return False
        try:
            import App
            game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
            player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
        except Exception:
            return False
        return player is not None and ship is player

    def CanFire(self) -> int:
        """Three gates:

          * ship alive — a dead ship's weapons never fire.
          * charge — ``> 0`` to start or sustain, EXCEPT that a bank which
            has run dry does not restart until it is back to
            MinFiringCharge.  Measured on the original exe: a Kessok beam
            preset to charge 3 with MinFiringCharge 4 fires at the full rate
            (stbc-oracle bible B8, `phaser_high_front_57_charge3`), so
            MinFiringCharge does not gate a fresh start; but the Galaxy's
            bank 5, drained to 0 at 6.6 s, had not relit at 0.45 by 12.5 s
            while the trigger stayed held (`phaser_galaxy_front_57`), so a
            depleted bank does latch.  The restart threshold itself is only
            bounded (> 0.45 on a 5-charge bank); MinFiringCharge is the one
            authored value in range.  Pulse cannons use affordability
            instead (one shot's cost, PulseWeapon._shot_cost).
          * disabled-product — the bank's own condition times the parent
            system's condition must clear the authored DisabledPercentage
            threshold (``GetOverallConditionPercentage`` in the audit); a
            damaged system throttles a healthy bank the same way a
            damaged bank throttles a healthy system.

        The existing parent-IsOn gate is unchanged (BC gates power
        elsewhere, not inside this predicate).

        The rule is the native one, fire control's one copy (fire_gates.cc
        can_fire; native_combat.k1_can_fire; fire control native only, M3,
        M8.6): this is the SDK's thin call into it, the latch clear
        included. A weapon the mirror cannot answer for cannot fire (0)."""
        return native_combat.k1_can_fire(self)

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when the beam is firing after this call.

        The SDK's Fire is a one-weapon native session (native_combat.k1_fire;
        k1_fire_control.h, THE SDK ROUTES, M8.6): the decision (CanFire, then
        the arc from this emitter's mount at the target centre, else ship
        forward) and its effect -- `_firing`, `_target`, `_target_offset`,
        and on the was-not-firing edge the beam-on countdown, the dwell, the
        fire sound and (a PhaserBank's) ET_WEAPON_FIRED, queued. Fire
        control has no Python copy (M3)."""
        return native_combat.k1_fire(self, target, offset)

    def StopFiring(self) -> None:
        # K0 (a bank drained dry), K1 (a bank its walk stops) and K2 (a
        # phaser step's stop) log these writes and queue the LOOP_STOP
        # themselves, from one encoding (native/src/combat/include/
        # dauntless/combat/stop_firing.h): change both together.
        was_firing = self._firing
        self._firing = False
        self._beam_on_countdown = 0.0
        if not was_firing:
            return
        if effect_queue.deferring():
            # Queued whether or not a loop plays yet: a FIRE_SOUND queued
            # this tick sets the handle at delivery, before this stops it.
            effect_queue.post(effect_queue.LOOP_STOP, self)
        else:
            self._stop_loop_sound()

    def _stop_loop_sound(self) -> None:
        """Stop and drop the bank's looped fire sound, if one plays."""
        if self._loop_handle is not None:
            self._loop_handle.Stop()
            self._loop_handle = None

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def IsBeamOn(self) -> bool:
        """True once a lit bank's beam-on delay has elapsed: it is now
        draining charge and accumulating damage dwell."""
        return self._firing and self._beam_on_countdown <= 0.0

    def accumulate_dwell(self, dt: float) -> float:
        """Advance the damage dwell by one frame; return the dwell to flush
        (> 0 only on a flush frame), having reset it.  The threshold is
        checked before this frame's dt is added — see BEAM_DWELL_FLUSH_S."""
        if not self.IsBeamOn():
            return 0.0
        if self._dwell > BEAM_DWELL_FLUSH_S:
            flushed, self._dwell = self._dwell + dt, 0.0   # the flush frame counts
            return flushed
        self._dwell += dt
        return 0.0

    def take_dwell(self) -> float:
        """Hand back whatever dwell has accumulated (a beam swept off its
        target or stopped delivers a final partial pulse — clean-room §12.4)
        and reset it."""
        flushed, self._dwell = self._dwell, 0.0
        return flushed

    # EnergyWeapon.{Get,Set}PowerSetting (SWIG surface; zero SDK call sites).
    # The EMITTER's own power field — consumed by PulseWeapon's per-shot
    # cost.  Not the PhaserSystem power level.
    def GetPowerSetting(self) -> int:
        return self._power_setting

    def SetPowerSetting(self, v) -> None:
        self._power_setting = max(0, min(2, int(v)))

    def _discharge_rate_per_second(self) -> float:
        """Charge-units per second drained while the beam is held.  Default
        reads the authored property; PhaserBank overrides with BC's
        power-level table (see PHASER_DISCHARGE_BY_POWER_LEVEL)."""
        return self._normal_discharge_rate

    def UpdateCharge(self, dt: float) -> None:
        if self._firing:
            if self._beam_on_countdown > 0.0:
                # Lit but not yet on: no drain until the beam-on delay is up.
                self._beam_on_countdown -= dt
                return
            self._charge_level = max(
                0.0, self._charge_level - self._discharge_rate_per_second() * dt
            )
            if self._charge_level <= 0.0:
                # Depletion auto-stop. BC's banks discharge all the way
                # to 0 while firing (visible on the WeaponsDisplay as the
                # full black → red → yellow → green sweep during recharge).
                # Latch: a restart needs MinFiringCharge (see CanFire).
                # Route via StopFiring so the looped SFX handle is silenced.
                self._depleted = True
                self.StopFiring()
        else:
            # HEADROOM FIRST. A fully-charged idle bank has nothing to do, and
            # measured at 100 ships that is 89.7% of every UpdateCharge call --
            # 709 of 790 per tick. Each of them used to pay GetParentSubsystem,
            # IsOn, GetNormalPowerPercentage and GetConditionPercentage (the
            # last two walk subsystem state) purely to arrive at a headroom of
            # zero and do nothing.
            #
            # Exactly equivalent: every test this jumps ahead of is a getter
            # with no side effects, and when headroom is zero the original
            # reached the same end state -- `want` would have been min(rate, 0)
            # and the += a no-op -- by either branch it could take.
            if self._max_charge - self._charge_level <= 0.0:
                return
            parent = self.GetParentSubsystem()
            if parent is None or parent.IsOn():
                power_factor = max(0.0, parent.GetNormalPowerPercentage()
                                    if parent is not None else 1.0)
                # Audited §1.6: recharge also scales with the bank's OWN
                # condition — a damaged bank recharges proportionally
                # slower.  (BC's audited non-local 1.25x boost near a
                # friendly starbase never triggers in single-player — no
                # code path applies it; documented here, not implemented.)
                condition_factor = self.GetConditionPercentage()
                headroom = self._max_charge - self._charge_level
                if headroom > 0.0:
                    want = min(self._recharge_rate * power_factor
                               * condition_factor * dt, headroom)
                    self._charge_level += want

    def _play_fire_sfx(self) -> None:
        """Play the firing bank's Start one-shot + Loop sustained tone.

        Both are attached to the firing ship's scene node so they
        position correctly in 3D space — the WAVs are LS_3D, but a bare
        Play() with no attach_node lands the source at world origin.
        Matches the pattern engine/audio/engine_rumble.py uses for ship-
        attached looping sounds.
        """
        name = _resolve_fire_sound(self.GetProperty())
        if not name:
            return
        from engine.audio.tg_sound import TGSoundManager
        mgr = TGSoundManager.instance()
        attach_node = self._firing_ship_node()

        priority = (LOCAL_FIRE_PRIORITY if self._is_local_player_ship()
                    else self._remote_fire_priority())

        start_snd = mgr.GetSound(name + " Start")
        if start_snd is None:
            # Tractor convention: bare name has no " Start"/" Loop" pair.
            start_snd = mgr.GetSound(name)
        if start_snd is not None:
            # Set-then-play on the SHARED named TGSound: GetSound(name) hands
            # back the same instance to every firer of this weapon type, but
            # SetPriority + Play happen back-to-back in this one call, so the
            # value latched into the backend at Play() time is always this
            # firer's -- see the report for why that ordering matters.
            start_snd.SetPriority(priority)
            start_snd.Play(attach_node=attach_node)

        loop_snd = mgr.GetSound(name + " Loop")
        if loop_snd is not None:
            loop_snd.SetLooping(True)
            loop_snd.SetPriority(priority - CO_FIRED_PRIORITY_STEP)
            self._loop_handle = loop_snd.Play(attach_node=attach_node)

        # "(null)" is what hardpoint editors write for "no sound" (DCMPv2
        # ships it); only a real name that nothing registered is news.
        if (start_snd is None and loop_snd is None
                and name.lower() != "(null)"):
            _announce_once(("fire sound", name),
                           "fire sound %r not registered -- those weapons "
                           "fire silently" % name)

    def _firing_ship_node(self):
        """Walk parent_subsystem → parent_ship → GetNode() for the sound anchor.

        Returns None (non-positional) when any link is missing. NOTE: this used
        to probe a `GetSceneNodeId` that exists nowhere in the SDK or App.py —
        our own invention. It resolved to a truthy `_Stub`, `int()` collapsed it
        to 0, and every weapon sound played unattached. The tests only passed
        because their fake ships defined the phantom.
        """
        parent_sys = self.GetParentSubsystem() if hasattr(self, "GetParentSubsystem") else None
        if parent_sys is None:
            return None
        parent_ship = parent_sys.GetParentShip() if hasattr(parent_sys, "GetParentShip") else None
        if parent_ship is None:
            return None
        getter = getattr(parent_ship, "GetNode", None)
        return getter() if getter is not None else None


def _cloak_blocks_fire(weapon_system) -> bool:
    """True when the owning ship is cloaked or mid-cloak, so it cannot fire.

    BC forces all weapons offline for as long as the cloak is engaged — you
    sacrifice offence for invisibility.  ``IsTryingToCloak()`` is true for both
    CLOAKING (fading out) and CLOAKED; a DECLOAKING ship is already committed to
    reappearing and may fire.  Cheap and raise-safe: ships with no cloak (the
    common case) climb to a None subsystem and fall straight through.
    """
    ship = (weapon_system.GetParentShip()
            if hasattr(weapon_system, "GetParentShip") else None)
    if ship is None:
        return False
    getter = getattr(ship, "GetCloakingSubsystem", None)
    if getter is None:
        return False
    cloak = getter()
    return cloak is not None and bool(cloak.IsTryingToCloak())


# warp_state imports ships, which imports this module, so it cannot be bound at
# import time. Resolved once on first use and cached (same cycle-breaking idea
# as engine/appc/ship_motion.py's module-scope imports, but lazy).
_warp_state_mod = None


def _warp_state():
    global _warp_state_mod
    if _warp_state_mod is None:
        from engine.appc import warp_state
        _warp_state_mod = warp_state
    return _warp_state_mod


def _dewarp_blocks_fire(weapon_system) -> bool:
    """True while the owning ship is sliding onto its warp-in placement
    (warp-in spec 6.1, "During the slide": it holds fire until it has fully
    arrived). Accepts any subsystem in the chain -- GetParentShip climbs.
    Our rule, not recovered BC behaviour."""
    ship = (weapon_system.GetParentShip()
            if ids.implements(weapon_system, "GetParentShip") else None)
    if ship is None:
        return False
    return _warp_state().is_arriving(ship)


def _target_undetectable(weapon_system, target) -> bool:
    """True when the firing ship cannot detect *target* (fully cloaked, nebula
    lock-break, or degraded/offline sensors).

    Mirrors the authoritative per-tick chokepoint in host_loop._advance_combat
    (``can_detect(ship, target)`` → ``bank.StopFiring()``) at the *fire-
    initiation* points, so the warm-up SFX never starts on a shot the damage
    tick would immediately drop. Without this gate, an AI (or held trigger)
    re-firing every tick at a cloaked target produces a start/stop/restart SFX
    loop — the "ship's horn" bug.

    Raise-safe and cheap: a positionless / sensorless fixture reads back the
    fallback sensor range from ``can_detect`` and is therefore detectable, so
    non-cloak tests are unaffected. A weapon with no resolvable parent ship is
    treated as detectable (no gate)."""
    if target is None:
        return False
    ship = (weapon_system.GetParentShip()
            if hasattr(weapon_system, "GetParentShip") else None)
    if ship is None:
        return False
    try:
        from engine.appc.sensor_detection import can_detect
        return not can_detect(ship, target)
    except Exception:
        return False


class Weapon(ShipSubsystem):
    """BC leaf emitter — sdk/Build/scripts/App.py:5758 `class Weapon(ShipSubsystem)`.

    Deliberately NOT a PoweredSubsystem: in BC a weapon has no power, no IsOn
    and no charge.  Power lives on the parent WeaponSystem; charge lives on
    EnergyWeapon (App.py:6426-6440), which torpedo tubes do not inherit.

    Surface the SDK actually calls on a leaf weapon.  IsMemberOfGroup, IsDumbFire,
    SetSkewFire, and IsSkewFire are now implemented for the BC-faithful dispatch
    tick (weapon-firing-mechanics.md §3.1/§2.10).  DELIBERATELY ABSENT (verified
    zero SDK call sites on a tube): SetFiring, GetTargetID,
    GetOverallConditionPercentage, IsInArc, CanHit.

    ⚠ "Zero SDK call sites" above was verified ON A TUBE, and that scoping
    matters: `CanHit` HAS one SDK call site, on a PhaserBank —
    Conditions/ConditionInPhaserFiringArc.py:175, live under FedAttack. It is
    implemented on PhaserBank (see PhaserBank.CanHit); only the tube lacks it.
    `IsInArc` genuinely has zero call sites and stays absent.

    The former claim that both were "unspecifiable — their BC signatures cannot
    be recovered from the SDK" is retired (2026-08-09): the clean-room reference
    publishes PhaserBank_CanHit at 0x00619030 alongside GetArcWidthAngles,
    GetArcHeightAngles and GetMaxPhaserRange, which is enough to specify it as a
    point-in-arc-cone-and-range test.

    GetProperty/SetProperty are inherited from ShipSubsystem (subsystems.py:273).
    """

    # Mirrored into the native combat row on every write (native_combat).
    _firing = NativeField(bool)
    _target = NativeRefField("Object")
    _target_offset = NativeField(native_combat.OFFSET)
    _fire_timer = NativeField(float)

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Seeded here, not in the subclass: IsFiring() must return a real 0 on a
        # fresh weapon.  Without this, __getattr__ hands back a truthy _Stub.
        self._firing: bool = False
        self._target = None
        self._target_offset = None
        # BC Weapon+0x9C — inter-shot delay accumulator for TryFireWeapon.
        self._fire_timer: float = 0.0

    def Fire(self, target=None, offset=None, **kwargs) -> None:
        """Discrete shot.  Subclasses implement — the payload differs per weapon."""
        raise NotImplementedError

    def CanFire(self) -> int:
        return 0

    def StopFiring(self) -> None:
        # K1 logs this write itself for a tube its walk stops (bank_stop,
        # k1_fire_control.cc, from stop_firing.h): change both together.
        self._firing = False

    def IsFiring(self) -> int:
        return 1 if self._firing else 0

    def FireDumb(self, iReserved=0, iForce=1) -> None:
        """SDK AI/Preprocessors.py:458 — `pTube.FireDumb(0, 1)`.  Unguided shot,
        no target.

        The AI calls this WITHOUT checking CanFire() first, so it must be a
        silent no-op when the weapon is NOT READY.  That contract is met by the
        implementing subclass: TorpedoTube.Fire returns early on `not CanFire()`.

        Deliberately NOT gated on CanFire() here.  Doing so would make a subclass
        that has not implemented Fire() silently do nothing forever, instead of
        raising NotImplementedError — trading a loud programming error for the
        silent-failure pattern this engine is riddled with.  "Not ready" is a
        runtime state and must no-op; "not implemented" is a bug and must shout.

        iReserved/iForce are kept for SDK signature compatibility and unused.

        Bypasses WeaponSystem.StartFiring, so the warp-in hold-fire gate is
        checked here too.

        K1 decides a tube's dumb fire (the gate from the mirrored
        `arriving` flag, then the tube's Fire and its launch;
        k1_fire_control.cc, dumb_fire): the SDK's call is a one-tube native
        session on that rule (native_combat.k1_dumb_fire; k1_fire_control.h,
        THE SDK ROUTES, M8.1). Fire control has no Python copy (M3).
        """
        native_combat.k1_dumb_fire(self)

    def CalculateRoughDirection(self) -> TGPoint3:
        """WORLD-space mount direction.  SDK AI/Preprocessors.py:456 and
        AI/PlainAI/IntelligentCircleObject.py:234.

        _climb_to_ship() — NOT GetParentShip().  ShipClass._attach_subsystem
        (ships.py:690-700) sets _parent_ship only on TOP-LEVEL subsystems.  A
        torpedo tube is a CHILD of the TorpedoSystem, so its _parent_ship is
        None and GetParentShip() would silently return None on every real tube.
        """
        return _emitter_world_direction(self, self._climb_to_ship())

    def CalculateWeaponAppeal(self) -> float:
        """SDK AI/PlainAI/IntelligentCircleObject.py:238.  The AI sums appeal
        across weapons facing a candidate heading and picks the best facing.

        BC's exact formula is not recoverable from the SDK, so this is an
        APPROXIMATION, not a reproduction: 1.0 for a functional weapon, 0.0 for
        a disabled one.  That yields "face the direction with the most working
        weapons", which matches the caller's intent.
        """
        return 0.0 if self.IsDisabled() else 1.0

    def IsMemberOfGroup(self, g) -> int:
        """Weapon::IsMemberOfGroup (0x00583240). Group ids are 1-BASED bits
        in the property's Groups mask; group 0 means 'all weapons'."""
        g = int(g)
        if g == 0:
            return 1
        prop = self.GetProperty()
        get = getattr(prop, "GetGroups", None) if prop is not None else None
        mask = get() if callable(get) else 0
        return 1 if (int(mask) & (1 << (g - 1))) else 0

    def IsDumbFire(self) -> int:
        """Weapon::IsDumbFire (0x00583270, property+0x48). Only torpedo
        tubes are dumbfire-capable in our surface (AI/Preprocessors.py:458)."""
        return 0


class WeaponSystem(PoweredSubsystem):
    """Weapon system — has firing state and an optional target.

    Reparented under PoweredSubsystem because every weapon system in BC
    has a power line.  See sdk/.../App.py:6361 (WeaponSystem inherits
    PoweredSubsystem there).

    Sequential firing (PR 2a): StartFiring picks the next eligible
    emitter in round-robin order, fires it, and advances the cursor.
    Matches Galaxy's SetSingleFire(1) loadout.  Multi-fire / firing-chain
    modes are future work (FiringChainString hardpoint field).
    """
    # Mirrored into the native combat row on every write (native_combat). The
    # leaf emitters that derive from WeaponSystem (PhaserBank, PulseWeapon,
    # TractorBeam) inherit _target / _target_offset / _fire_timer from here.
    _target = NativeRefField("Object")
    _target_offset = NativeField(native_combat.OFFSET)
    _fire_timer = NativeField(float)
    _fire_held = NativeField(bool)
    _held_target = NativeRefField("Object")
    _held_offset = NativeField(native_combat.OFFSET)
    # An in-place append (_add_target) calls native_combat.push_field.
    _target_list = NativeRefList("Object")
    _force_update = NativeField(bool)
    _last_weapon_idx = NativeField(int)
    _last_group_fired = NativeField(int)
    _firing_chain_mode = NativeField(int)
    _group_fire_mode = NativeField(int)
    _single_fire = NativeField(int)

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._target = None
        # A NativeField has no __get__: unassigned, a read would return the
        # descriptor itself (truthy, not a TGPoint3).
        self._target_offset = None
        self._weapon_system_type: int = 0
        # Round-robin cursor into child emitters (the K1 tractor walk's
        # engage, mirrored on TractorBeamSystem; the BC tick uses
        # _last_weapon_idx below instead).
        self._next_emitter_index: int = 0
        # ── BC tick state (weapon-firing-mechanics.md §3.1-3.3) ──────────
        self._force_update: bool = False    # +0xAC: bypass 0.33s delay this tick
        self._group_fire_mode: int = 0      # +0xB0: published working group
        self._last_weapon_idx: int = -1     # +0xB4: round-robin cursor
        self._firing_chain_mode: int = 0    # +0xB8: active chain index
        self._last_group_fired: int = -1    # +0xBC: resume input, -1 sentinel
        self._target_list: list = []        # +0xC4: pruned per tick
        self._fire_timer: float = 0.0       # BC Weapon+0x9C: inter-shot delay
        # Held-trigger state (press = StartFiring arms, release = StopFiring
        # disarms).  host_loop._pump_held_weapons runs native fire control's
        # walk (native_combat.k1_pump) once per tick for every system with
        # _fire_held set.
        self._fire_held: bool = False
        self._held_target = None
        self._held_offset = None
        # Read by native fire control's walk (stop after the first success
        # when set).
        # Copied from the authored WeaponSystemProperty by ships.py's
        # property→system pass via SetSingleFire below.
        self._single_fire: int = 0

    def GetSingleFire(self) -> int:                 return self._single_fire

    def SetSingleFire(self, v) -> None:
        """Lives on the BASE class deliberately: ships.py's property→system
        copy calls SetSingleFire on every system type behind a hasattr guard
        that is ALWAYS true through the _Stub — while this lived only on
        _HeldFireWeaponSystem, TorpedoSystem silently dropped its authored
        value (stub heatmap rank 33, 212 hits). Stock torpedo systems author
        SetSingleFire(0) so the miss was benign, but only by coincidence."""
        self._single_fire = int(v)

    def ShouldBeAimed(self) -> int:
        """Does this weapon system have to bear on the target to fire?

        Decompiled stbc.exe (WeaponSystem::ShouldBeAimed, 0x00584070):

            iVar1 = FUN_00584050();                    // this->GetProperty()
            return *(undefined1 *)(iVar1 + 0x51);      // property->m_bAimedWeapon

        i.e. it is *purely* a read of the authored WeaponSystemProperty
        flag written by SetAimedWeapon (+0x51) — no per-class constant, no
        separate storage. The property ctor (0x0069afe0) defaults it to 0,
        and TorpedoSystemProperty's ctor (0x00693f60) does not override it,
        so an unauthored system is free-fire for every weapon type.

        Consumer: AI/Preprocessors.py:642-647 (FireScript.CheckGoodShot)
        skips the whole directional check when this is false.
        """
        prop = self.GetProperty()
        # getattr-with-default, not hasattr: our leaf emitters (PhaserBank,
        # TorpedoTube) also inherit WeaponSystem but carry a PhaserProperty /
        # TorpedoTubeProperty, which has no AimedWeapon byte. The SDK only
        # asks the aggregator, so falling back to the ctor default is inert.
        is_aimed = getattr(prop, "IsAimedWeapon", None)
        if is_aimed is None:
            return 0
        return is_aimed()

    def IsDumbFire(self) -> int:
        """Weapon systems are not dumbfire-capable by default. Only TorpedoTube
        (which is a Weapon, not a system) overrides this to return 1."""
        return 0

    def IsSkewFire(self) -> int:
        """Skew-salvo is a TorpedoTube concept; leaf emitters that are
        WeaponSystem subclasses (PulseWeapon, PhaserBank, TractorBeam) never
        skew. Hoisted here — same hierarchy trap as IsDumbFire/SetSingleFire —
        so a skew probe (the mirror's row push) reaches a real 0 instead of the
        truthy _Stub (stub-heatmap row PulseWeapon.IsSkewFire; harmless today
        only because the isinstance(GetRight(), TGPoint3) guard masks it)."""
        return 0

    def IsMemberOfGroup(self, g) -> int:
        """WeaponSystem::IsMemberOfGroup (0x00583240). Group ids are 1-BASED bits
        in the property's Groups mask; group 0 means 'all weapons'.

        Inherited by PhaserBank, PulseWeapon, TractorBeam (leaf emitters that are
        also WeaponSystem subclasses)."""
        g = int(g)
        if g == 0:
            return 1
        prop = self.GetProperty()
        get = getattr(prop, "GetGroups", None) if prop is not None else None
        mask = get() if callable(get) else 0
        return 1 if (int(mask) & (1 << (g - 1))) else 0

    def SetForceUpdate(self, flag) -> None:  self._force_update = bool(flag)
    def GetForceUpdate(self) -> int:         return 1 if self._force_update else 0

    def GetFiringChains(self) -> list:
        prop = self.GetProperty()
        get = getattr(prop, "GetFiringChains", None) if prop is not None else None
        chains = get() if callable(get) else []
        return chains if isinstance(chains, list) else []

    def SetFiringChainMode(self, n) -> None:
        """WeaponSystem::SetFiringChainMode (0x00584FA0): clamped below the
        chain count. This is what BC's tactical 'torpedo spread' toggle calls."""
        chains = self.GetFiringChains()
        hi = max(0, len(chains) - 1)
        self._firing_chain_mode = max(0, min(int(n), hi))

    def GetFiringChainMode(self) -> int:     return self._firing_chain_mode

    def SetGroupFireMode(self, g) -> None:   self._group_fire_mode = int(g)
    def GetGroupFireMode(self) -> int:       return self._group_fire_mode

    def _active_chain_groups(self) -> list:
        """Ordered group ids of the active chain; [0] ('all weapons') when
        the ship authors no chains (67 of 70 stock hardpoints)."""
        chains = self.GetFiringChains()
        if not chains:
            return [0]
        _label, groups = chains[self._firing_chain_mode % len(chains)]
        return list(groups) if groups else [0]

    def _add_target(self, target) -> None:
        if target is not None and target not in self._target_list:
            self._target_list.append(target)
            native_combat.push_field(self, "_target_list")  # in-place append

    def GetNumTargets(self) -> int:          return len(self._target_list)

    def IsInTargetList(self, target) -> int:
        """SDK AI/PlainAI/StarbaseAttack.py:114. Must be a real int: a stub
        here is truthy, so `if not IsInTargetList(t): StartFiring(t)` never
        fired (heatmap 116). Identity, not `in` (which is `==` under the
        hood): `_Stub.__eq__` (engine/core/ids.py) returns
        `isinstance(o, _Stub)`, so any two stubs compare equal and a stub
        target would read as "in the list" against any stub entry."""
        if target is None:
            return 0
        return 1 if any(t is target for t in self._target_list) else 0

    # ── Parent-aggregator predicates ───────────────────────────────────
    # WeaponSystem parents own their hardpoint emitters (PhaserBank,
    # TorpedoTube, PulseWeapon, TractorBeam) as _children. Damage lands
    # on the children via apply_hit's spherical-splash loop, which walks
    # every non-hull subsystem and weights damage by proximity to the
    # impact point; the parent surfaces aggregated state to SDK/UI
    # consumers without storing its own condition pool.
    #
    # Locked semantics from the combat damage pipeline roadmap:
    #   IsDamaged   = self._damaged or any(c.IsDamaged() or c.IsDestroyed() for c in children)
    #   IsDisabled  = children and all(c.IsDisabled()  for c in children)
    #   IsDestroyed = self._destroyed or (children and all(c.IsDestroyed() for c in children))
    #
    # Empty-children edge: a weapon system with no hardpoints falls
    # through to the condition-based ShipSubsystem predicates. A default-
    # constructed parent (condition == max_condition) still reports zero;
    # leaf emitters with damaged condition report the damage themselves.

    def IsDamaged(self) -> int:
        if not self._children:
            # Leaf emitter (no sub-hardpoints): use condition-based predicate.
            return ShipSubsystem.IsDamaged(self)
        if self._damaged:
            # Honour the explicit flag set by ShipSubsystem.SetDamaged.
            return 1
        for c in self._children:
            if c.IsDamaged() or c.IsDestroyed():
                return 1
        return 0

    def IsDisabled(self) -> int:
        if not self._children:
            # Leaf emitter: use condition-based predicate.
            return ShipSubsystem.IsDisabled(self)
        for c in self._children:
            if not c.IsDisabled():
                return 0
        return 1

    def IsDestroyed(self) -> int:
        if not self._children:
            # Leaf emitter: use condition-based predicate.
            return ShipSubsystem.IsDestroyed(self)
        if self._destroyed:
            # Honour the explicit flag set by ShipSubsystem.SetDestroyed.
            return 1
        for c in self._children:
            if not c.IsDestroyed():
                return 0
        return 1

    def StartFiring(self, target=None, offset=None) -> None:
        """Arms the tick (BC StartFiring reads no spread/skew state — §2.10).
        The actual dispatch is the native K1 walk, pumped per frame by
        host_loop._pump_held_weapons; SetForceUpdate(1) + one immediate
        update makes a tap fire this frame (SDK FireWeapons does exactly
        StartFiring + SetForceUpdate(1))."""
        if not self.IsOn():
            return
        # Disabled-weapons gate: when every child reports disabled (Project 2
        # aggregation), the parent IsDisabled is 1 — block fire. Spec §4.2.
        if _is_offline(self):
            return
        # Cloak gate: a cloaked / cloaking ship cannot fire (BC rule).
        if _cloak_blocks_fire(self):
            return
        # Warp-in gate: an arriving ship holds fire until it has landed.
        if _dewarp_blocks_fire(self):
            return
        # Detectability gate: never fire (nor play warm-up SFX) at a target the
        # ship can't detect — cloaked, nebula-hidden, or out of sensor range.
        if _target_undetectable(self, target):
            return
        # Engageability gate (per-class hook, e.g. PhaserSystem's global fire
        # range): an out-of-range trigger must NOT latch _fire_held — an AI
        # re-calls StartFiring every tick, and a latched-but-unengageable held
        # state would flicker fire/stop each frame (the "ship's horn" loop).
        if (target is not None and hasattr(self, "_can_engage")
                and not self._can_engage(self.GetParentShip(), target)):
            return
        self._add_target(target)
        self._held_target = target
        self._held_offset = offset
        self._fire_held = True
        self.SetForceUpdate(1)
        # One immediate update (dt 0), walked by the native K1 kernel:
        # Python runs only its effects (native_combat.k1_system).
        native_combat.k1_system(self, 0.0)

    def StopFiring(self, *args) -> None:
        # K1 (the pump's system_stop) and K2 (an offline phaser system's
        # stop) log these writes, then each child's stop (stop_firing.h,
        # a firing child's LOOP_STOP queued), themselves
        # (k1_fire_control.cc, k2_beams.cc): change all three together.
        self._fire_held = False
        self._held_target = None
        self._held_offset = None
        self._target_list = []
        self._last_group_fired = -1
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "StopFiring"):
                w.StopFiring()

    def StopFiringAtTarget(self, pTarget) -> None:
        """SDK Preprocessors.py:274/469 — alias for StopFiring() since
        headless doesn't model multi-target firing state."""
        self.StopFiring()

    def IsFiring(self) -> int:
        if self._fire_held:
            return 1
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "IsFiring") and w.IsFiring():
                return 1
        return 0

    def GetTarget(self):                          return self._target
    def SetTarget(self, target) -> None:          self._target = target
    def GetWeaponSystemType(self) -> int:         return self._weapon_system_type
    def SetWeaponSystemType(self, v) -> None:     self._weapon_system_type = int(v)

    # SDK-faithful aliases over the child-subsystem API.
    # TacticalInterfaceHandlers.FireWeapons (PR 2) reads these.
    def GetNumWeapons(self) -> int:               return self.GetNumChildSubsystems()
    def GetWeapon(self, i: int):                  return self.GetChildSubsystem(i)

    # ── BC tick engine (weapon-firing-mechanics.md §3.2/§3.3) ───────────────
    # StartFiring (above) arms the tick and host_loop._pump_held_weapons
    # walks every armed system once per frame: the native K1 kernel's walk
    # (k1_fire_control.cc), fire control's one copy (fire control native
    # only, M3). Its inter-shot threshold is FIRE_TIMER_THRESHOLD.

class TorpedoAmmoType:
    """A loaded torpedo ammo type — exposes the SDK GetAmmoName surface.

    Real BC Appc has a TorpedoAmmoType class with per-instance ammo properties
    (damage, blast radius, etc.); Phase 1 only needs the name for the
    MissionLib.SetTotalTorpsAtStarbase / LoadTorpedoes lookup pattern, which
    compares ``pTorpType.GetAmmoName() == "Photon"``.
    """
    # Mirrored into the native combat row on every write (native_combat).
    # _max_torpedoes is AddAvailable's clamp (K1's native launch debits).
    _unlimited = NativeField(bool)
    _available = NativeField(int)
    _max_torpedoes = NativeField(int)

    def __init__(self, name: str, launch_speed: float = 0.0, power_cost: float = 0.0,
                 max_torpedoes=None, script=None):
        native_combat.register(self, "Ammo")
        self._name = name
        # SDK TorpedoRun.py:130 / StationaryAttack.py:78 use launch speed to
        # predict the torpedo's intercept point.  Real BC tunes this per ammo
        # type via the hardpoint scripts; Phase 1 keeps a single scalar.
        self._launch_speed = float(launch_speed)
        # SDK Preprocessors.py:563 reads GetPowerCost() to *rate* ammo types;
        # the C++ Appc engine also bills it from PowerSubsystem each shot.
        # Sourced from the projectile script's GetPowerCost() at seed time.
        self._power_cost = float(power_cost)
        # Projectile module path (SDK App.py:9574 TorpedoAmmoType.GetTorpedoScript),
        # read by AI/Preprocessors.py:566,714.
        self._script = script
        # ── Reserve accounting (SDK GetMaxTorpedoes / GetNumAvailableTorpsToType).
        # max_torpedoes is the hardpoint's SetMaxTorpedoes(slot, n) for this slot.
        # ``None`` marks an UNDECLARED slot (legacy hulls / the Photon fallback):
        # the reserve is inert — no fire gate, no decrement — so those firing
        # paths stay byte-identical.  A declared int (incl. 0) is finite; the type
        # spawns fully loaded (ships are combat-ready; IsFullyLoaded true at start).
        self._unlimited = max_torpedoes is None
        self._max_torpedoes = 0 if max_torpedoes is None else int(max_torpedoes)
        self._available = self._max_torpedoes
        # Its script's launch, read now (native combat: launch deferral
        # Task 5), so its first launch is native too.
        native_combat.push_ammo_launch(self)

    def GetAmmoName(self) -> str:
        return self._name

    def GetMaxTorpedoes(self) -> int:
        """SDK App.py:9572 — this type's capacity (MissionLib.IsFullyLoaded /
        SetMaxTorpsForPlayer compare against it)."""
        return self._max_torpedoes

    def SetMaxTorpedoes(self, n) -> None:
        # Declaring a max makes the type finite (App.py:9573).
        self._max_torpedoes = int(n)
        self._unlimited = False
        if self._available > self._max_torpedoes:
            self._available = self._max_torpedoes

    def GetTorpedoScript(self):
        return self._script

    def SetTorpedoScript(self, script) -> None:
        self._script = script
        native_combat.push_ammo_launch(self)

    def GetAvailable(self) -> int:
        """Rounds currently loaded for this type — the value the system exposes
        as GetNumAvailableTorpsToType(slot)."""
        return self._available

    def SetAvailable(self, n) -> None:
        n = int(n)
        self._available = n if self._unlimited else max(0, min(n, self._max_torpedoes))

    def AddAvailable(self, delta) -> None:
        """Load (+) or expend (-) rounds, clamped to [0, max].  No-op for an
        unlimited (undeclared-max) type. K1 logs a launch's AddAvailable(-1)
        itself (k1_fire_control.cc, log_launch): change both."""
        if self._unlimited:
            return
        self._available = max(0, min(self._available + int(delta), self._max_torpedoes))

    def GetLaunchSpeed(self) -> float:
        """SDK TorpedoRun.py:130 — used to predict torpedo intercept points."""
        return float(self._launch_speed)

    def GetPowerCost(self) -> float:
        """SDK App.py:9570 — per-shot power debit billed against the firing
        ship's PowerSubsystem.  Stock values: Photon=20, Quantum=30,
        Klingon=40, PhasedPlasma=40, Cardassian=10, FusionBolt=10,
        PositronTorpedo=10, KessokDisruptor=30 — see
        sdk/Build/scripts/Tactical/Projectiles/*.py."""
        return float(self._power_cost)

    def __repr__(self) -> str:
        return f"<TorpedoAmmoType {self._name!r}>"


class TorpedoSystem(WeaponSystem):
    # Mirrored into the native combat row on every write (native_combat).
    # _ammo_by_slot is mutated in place by AddAmmoType / RemoveAmmoType, which
    # call native_combat.push_field.
    _last_system_fire_time = NativeField(float)
    _selected_slot = NativeField(native_combat.OPT_INT)
    _ammo_by_slot = NativeSlotMap()

    def __init__(self, name: str = ""):
        super().__init__(name)
        # Keyed slot table, populated by AddAmmoType during hardpoint setup.
        # SetAmmoType(index) SELECTS a slot (mission/AI ammo switching);
        # it never writes here.  GetNumAmmoTypes counts populated slots.
        self._ammo_by_slot: dict = {}
        # Selected ammo slot.  None == "lowest populated slot" (the historical
        # default); an int selects that slot when it is populated.  UI type
        # cycling (weapon_config.cycle_torpedo_type) drives this via
        # SetCurrentAmmoSlot / CycleAmmoType so both the readout and the
        # per-shot power cost track the chosen type.
        self._selected_slot = None
        # Ship-wide fire stagger (Task 7, audited): GAME time of the last
        # torpedo launched by ANY tube on this system.  A fresh system inits
        # to -1000.0 (same convention as TorpedoTube._last_fire_time) so the
        # first shot always passes the 0.5s stagger gate.  Skew-fire tubes
        # are exempt (TorpedoTube.CanFire checks IsSkewFire() first).
        self._last_system_fire_time: float = -1000.0

    def StartFiring(self, target=None, offset=None) -> None:
        """Arm the BC tick (base StartFiring) behind the ammo reserve gate.

        A finite ammo type (hardpoint-declared max) with no rounds left cannot
        fire; unlimited/undeclared types never gate.  The per-launch ammo debit
        is native fire control's launch (k1_fire_control.cc; one round per
        torpedo actually launched).  Launches chain across tubes via firing_chain walk-out with
        stagger delay, each firing straight out the tube's authored direction
        (BC-faithful per §2.4.1), never aimed at a target."""
        ammo = self.GetCurrentAmmoType()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        if finite and ammo.GetAvailable() <= 0:
            self._post_cant_fire()
            return
        super().StartFiring(target, offset)

    def _post_cant_fire(self) -> None:
        """Announce a torpedo fire attempt that cannot produce a launch.

        Gap #1 in docs/reference/engine/event-emitter-gaps.md. The event carries no
        reason: both SDK handlers (Bridge/TacticalMenuHandlers.py:1990,
        Bridge/TacticalCharacterHandlers.py:198) re-derive it from this
        system's own state via GetNumReady() / GetNumAvailableTorpsToType(),
        and both self-guard -- they fall through silently when tubes are
        ready, and they carry their own cooldowns (2 s global; 10 s since
        Tactical last spoke). So an emitter here cannot spam a line even if
        the player holds the trigger.

        Scoped to torpedoes on purpose. Both handlers cast the source to
        phaser and tractor systems as well and then use neither, so posting
        from the phaser/tractor gates would be observationally inert today
        while committing us to a reading of "can't fire" that no SDK code
        exercises.

        DELIBERATELY UNGUARDED, unlike the other emitters in this file
        (_post_weapon_fired, _broadcast_weapon_fire_failed,
        _broadcast_ammo_consumed_if_player), which wrap AddEvent in
        try/except + dev_mode.log_swallowed. Those fire on the hot per-shot
        path for consumers that already work; this one's consumers have NEVER
        ONCE RUN in this engine, because nothing posted the event until now.
        Swallowing here would hide the first real signal of a bug in code
        that has never executed -- the same reasoning, verbatim, that
        ships.py:1599 gives for posting ET_TARGET_WAS_CHANGED unguarded, and
        that events.py:AddEvent gives for leaving destination dispatch
        unguarded in general. Revisit once these handlers are live-verified.
        """
        # ET_CANT_FIRE IS ET_WEAPON_FIRE_FAILED, a queued kind -- but this is
        # reached only from StartFiring, never while the effect queue
        # defers, so it posts at once (an in-scope post would split the
        # kind; under tests and --developer it raises instead).
        effect_queue.check_acting_directly("ET_CANT_FIRE")
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_CANT_FIRE)
        evt.SetSource(self)
        # Posts even when GetParentShip() is None, unlike
        # TractorBeamSystem._sync_firing_event, which RETURNS on a null parent.
        # The difference is deliberate, not drift: that one holds an EDGE
        # (_was_firing), so posting-and-forgetting a parentless transition
        # would consume the crossing and lose the event permanently. This one
        # holds no state -- a can't-fire is a momentary fact, re-derivable on
        # the next trigger pull -- so there is nothing to defer and nothing to
        # lose.
        evt.SetDestination(self.GetParentShip())
        App.g_kEventManager.AddEvent(evt)

    def GetNumAmmoTypes(self) -> int:
        return len(self._ammo_by_slot)

    # ── SDK ammo-type curation surface (all int-slot indexed) ─────────────────
    # QuickBattle.py:2924 prunes, missions (E3M1) load, MissionLib iterates.
    def RemoveAmmoType(self, slot) -> None:
        """Drop the ammo type at ``slot`` (QuickBattle.py:2924 removes every
        slot past index 1 to strip PhasedPlasma).  QuickBattle removes top-down
        within a single snapshot loop, so no interior gap survives for stock
        hulls and GetNumAmmoTypes()==len stays contiguous."""
        slot = int(slot)
        if slot in self._ammo_by_slot:
            del self._ammo_by_slot[slot]
            native_combat.push_field(self, "_ammo_by_slot")   # in-place del
            if self._selected_slot == slot:
                self._selected_slot = None

    def LoadAmmoType(self, slot, count) -> int:
        """Load (+) / unload (-) ``count`` rounds into the type at ``slot``
        (E3M1.py, MissionLib.LoadTorpedoes).  Clamped to [0, max] by the type.

        Returns the LEFTOVER — how many of the requested rounds could NOT be
        loaded.  Not decoration: ``Actions.ShipScriptActions.ReloadShip``:394-395
        hands the starbase's stock over a type at a time and puts the remainder
        back, so returning ``None`` crashed the whole starbase dock sequence with
        ``TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'``::

            iLoadAtStarbase = iLoadAtStarbase - iTorpsToLoad   # stock not offered
            iLoadLeftover   = pTorpSys.LoadAmmoType(iType, iTorpsToLoad)
            SetCurrentStarbaseTorpedoLoad(iType, iLoadLeftover + iLoadAtStarbase)

        The contract that arithmetic encodes is conservation: every torpedo is
        either aboard the ship or still at the starbase, never both and never
        neither.  So measure what the type actually absorbed rather than
        re-deriving the clamp here — the type owns its own [0, max] rule, and an
        undeclared-max (``_unlimited``) type absorbs nothing at all, which this
        reports honestly as "all leftover" so the mission's starbase stock stays
        consistent instead of quietly swallowing rounds into an inert reserve.
        An absent slot likewise keeps the whole request at the starbase; claiming
        0 there would DELETE the stock.
        """
        requested = int(count)
        ammo = self.GetAmmoType(slot)
        if ammo is None or not ids.implements(ammo, "AddAvailable"):
            return requested
        before = ammo.GetAvailable()
        ammo.AddAvailable(requested)
        return requested - (ammo.GetAvailable() - before)

    def GetNumReady(self) -> int:
        """Number of child tubes currently loaded and ready to launch.

        BC's own handlers call this on the SYSTEM
        (Bridge/TacticalMenuHandlers.py:2007,
        Bridge/TacticalCharacterHandlers.py:223) to separate "out of
        torpedoes" from "not reloaded yet". Ours defined GetNumReady only on
        TorpedoTube (:2378), so a system-level call resolved through
        TGObject.__getattr__ to a truthy _Stub and neither handler could take
        the branch it wanted.
        """
        ready = 0
        for i in range(self.GetNumWeapons()):
            tube = self.GetWeapon(i)
            if tube is not None and tube.GetNumReady():
                ready += 1
        return ready

    def GetNumAvailableTorpsToType(self, slot) -> int:
        """Rounds currently loaded for the type at ``slot`` (E3M1.py:2888,
        MissionLib.IsFullyLoaded).  0 when the slot is absent."""
        ammo = self.GetAmmoType(slot)
        if ammo is not None and hasattr(ammo, "GetAvailable"):
            return ammo.GetAvailable()
        return 0

    def FillAmmoType(self, slot) -> None:
        """Top the type at ``slot`` back up to its max (SDK App.py:5981)."""
        ammo = self.GetAmmoType(slot)
        if ammo is not None and hasattr(ammo, "SetAvailable"):
            ammo.SetAvailable(ammo.GetMaxTorpedoes())

    def IsAmmoTypeSelectable(self, slot) -> bool:
        """Whether the type at ``slot`` can be selected/cycled to.

        BC gates the torpedo-type selector on availability, NOT declaration:
        ``GetNumAvailableTorpsToType(iType) > 0`` (AI/Preprocessors.py:537
        ChooseTorpType; the C++ HUD cycler uses the same rule).  So a slot
        declared with SetMaxTorpedoes(slot, 0) — e.g. a Sovereign's PhasedPlasma
        — is present in GetNumAmmoTypes() but never selectable, in missions as
        well as QuickBattle (which additionally hard-removes it).

        Our synthetic UNLIMITED types (the undeclared-max fallback for legacy /
        test hulls) report 0 available but represent an inexhaustible supply, so
        they always count as selectable."""
        ammo = self.GetAmmoType(slot)
        if ammo is None:
            return False
        if getattr(ammo, "_unlimited", False):
            return True
        return self.GetNumAvailableTorpsToType(slot) > 0

    def GetSelectableAmmoSlots(self) -> list:
        """Sorted slots the player can actually select — the live Type menu."""
        return [s for s in sorted(self._ammo_by_slot.keys())
                if self.IsAmmoTypeSelectable(s)]

    def GetCurrentAmmoTypeNumber(self) -> int:
        """SDK App.py:5977 — index of the selected ammo type."""
        return self.GetCurrentAmmoSlot()

    def GetAmmoTypeNumber(self) -> int:
        """SDK App.py:5985 alias used by Bridge handlers."""
        return self.GetCurrentAmmoSlot()

    def AddAmmoType(self, ammo_type) -> None:
        # Append into the next free slot.  This is the only writer of the
        # slot table (hardpoint setup); SetAmmoType merely selects a slot.
        self._ammo_by_slot[len(self._ammo_by_slot)] = ammo_type
        native_combat.push_field(self, "_ammo_by_slot")       # in-place store

    def SetAmmoType(self, ammo_index, _reload_arg=0) -> None:
        # SDK semantics: SELECT the ammo type at index `ammo_index` (0-based,
        # same domain as GetAmmoTypeNumber / range(GetNumAmmoTypes())).  Never
        # a store — hardpoint setup populates slots via AddAmmoType.  Call
        # sites: AI/Preprocessors.py:548,640 (int index from ChooseTorpType),
        # ShipScriptActions.py:400, MissionLib.py:611, E2M0.py:720
        # (App.AT_TWO = 1).  Second arg is always 0 in the SDK (reload
        # time/flag) — accepted, ignored.
        #
        # Switching to a DIFFERENT type unloads every tube: measured on the
        # original exe (stbc-oracle bible §4 T4, `torpedo_sovereign_quantum_57`)
        # the Sovereign's first quantum salvo after SetAmmoType(1) needs ~45 s
        # — its ReloadDelay is 40 s — and BC's decompiled switch path calls the
        # tube's unload (TorpedoTube.UnloadTorpedo, FUN_0057D9A0). Re-selecting
        # the type already loaded is left alone: every starbase dock ends with
        # SetAmmoType(GetAmmoTypeNumber(), 0), and emptying the tubes on that
        # is not something the capture shows.
        before = self.GetCurrentAmmoSlot()
        self.SetCurrentAmmoSlot(int(ammo_index))
        if self.GetCurrentAmmoSlot() != before:
            for i in range(self.GetNumWeapons()):
                tube = self.GetWeapon(i)
                unload = getattr(tube, "UnloadTorpedo", None)
                if not callable(unload):
                    continue
                ready = getattr(tube, "GetNumReady", None)
                n = int(ready()) if callable(ready) else 0
                for _ in range(n):
                    unload()

    def GetAmmoType(self, slot: int):
        return self._ammo_by_slot.get(int(slot))

    def GetCurrentAmmoType(self):
        """SDK TorpedoRun.py:130 / StationaryAttack.py:78 — returns the
        currently-selected ammo type, or None if no ammo configured.

        Returns the selected slot's ammo when SetCurrentAmmoSlot / CycleAmmoType
        has chosen a populated slot; otherwise falls back to the lowest-numbered
        loaded slot (the historical default, preserved so pre-selection callers
        are byte-identical)."""
        if not self._ammo_by_slot:
            return None
        return self._ammo_by_slot[self.GetCurrentAmmoSlot()]

    def GetCurrentAmmoSlot(self) -> int:
        """The effective ammo slot: the explicit selection when set and
        populated, else the lowest populated slot.  Returns -1 when no ammo
        is loaded at all."""
        if not self._ammo_by_slot:
            return -1
        if self._selected_slot is not None and self._selected_slot in self._ammo_by_slot:
            return self._selected_slot
        return min(self._ammo_by_slot.keys())

    def SetCurrentAmmoSlot(self, slot) -> None:
        """Select the given ammo slot.  Ignored silently when the slot is not
        populated (leaves the current selection unchanged)."""
        slot = int(slot)
        if slot in self._ammo_by_slot:
            previous = self.GetCurrentAmmoSlot()
            self._selected_slot = slot
            self._announce_player_type_change(previous)

    def CycleAmmoType(self) -> None:
        """Advance the selection to the next SELECTABLE slot (available > 0 or
        unlimited; sorted, wraps).  No-op with 0 or 1 selectable slots — so an
        empty declared type (e.g. PhasedPlasma, max 0) is skipped, never landed
        on."""
        slots = self.GetSelectableAmmoSlots()
        if len(slots) <= 1:
            return
        current = self.GetCurrentAmmoSlot()
        try:
            idx = slots.index(current)
        except ValueError:
            idx = 0
        self._selected_slot = slots[(idx + 1) % len(slots)]
        self._announce_player_type_change(current)

    def _announce_player_type_change(self, previous_slot) -> None:
        """Post ET_PLAYER_TORPEDO_TYPE_CHANGED so Felix speaks the switch.

        Called from the only two deliberate-selection writers above.  Deliberately
        NOT from the slot-removal path (``RemoveAmmoType`` clearing a selected
        slot): QuickBattle hard-removes a Sovereign's empty PhasedPlasma at setup,
        and that is curation, not the player switching weapon.

        Two gates, both load-bearing:

        * **Only on a real change.**  ``Actions.ShipScriptActions.ReloadShip``:400
          ends every starbase dock with ``SetAmmoType(GetAmmoTypeNumber(), 0)`` —
          re-selecting whatever is already current — so announcing unconditionally
          would have Felix report a torpedo switch each time the player docks.
          Compare against the EFFECTIVE previous slot (``GetCurrentAmmoSlot`` falls
          back to the lowest loaded slot before anything is selected), not the raw
          ``_selected_slot``, or the first real selection on a fresh system fires
          spuriously.
        * **Only for the player.**  BC's ET_PLAYER_ prefix is a locality gate, the
          same rule ``_broadcast_ammo_consumed_if_player`` already follows.  The
          SDK registers this handler on the player instance only, so an NPC's
          event could not be heard anyway — but posting it per NPC ammo switch
          (AI/Preprocessors ChooseTorpType) is pure noise on the queue.

        Source = this system (the SDK casts it with ``TorpedoSystem_Cast``);
        destination = the ship (what the SDK registered on).
        """
        if self.GetCurrentAmmoSlot() == previous_slot:
            return
        import App
        ship = self.GetParentShip()
        try:
            if ship is None or ship is not App.Game_GetCurrentPlayer():
                return
        except Exception:
            return
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_PLAYER_TORPEDO_TYPE_CHANGED)
            evt.SetSource(self)
            evt.SetDestination(ship)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed(
                "ET_PLAYER_TORPEDO_TYPE_CHANGED broadcast", _e)

    def SetSkewFire(self, flag) -> None:
        """Pure broadcast to child tubes (0x0057B1C0) — NO system-level
        state; audited §2.10. Dormant in stock play (zero SDK call sites)."""
        for i in range(self.GetNumWeapons()):
            w = self.GetWeapon(i)
            if w is not None and hasattr(w, "SetSkewFire"):
                w.SetSkewFire(flag)

    def SetFiringChainMode(self, n) -> None:
        """Wire BC's INTENDED torpedo-spread <-> skew-fire connection
        (2026-07-15 decomp update).

        The BC SDK's Model Property Editor documentation (modelpropertyeditor
        .html:255) says of a torpedo tube's Right vector: "the right vector
        will be used to change the firing direction slightly if torpedoes
        are fired in non-single-fire mode" — i.e. selecting a non-Single
        firing chain was ALWAYS meant to arm skew fire. Retail shipped this
        disconnected: the intended hook is a vtable-only salvo setter
        (0x0057B1F0) with zero callers anywhere in stbc.exe. Dauntless
        deliberately wires the intended design over the shipped bug: a
        non-Single chain fans a true simultaneous salvo (skew tubes are
        exempt from the 0.5s ship-wide stagger — see TorpedoTube.CanFire —
        so every member of the active chain group launches in the same
        tick, geometry from each tube's authored Right vector); Single
        restores BC's shipped walk-out.

        [0] is BOTH the chainless fallback and the SDK-documented "group of
        all weapons, single-firing" (i.e. authored Single) — either way it
        means single-fire, so it's the one case that must clear skew rather
        than set it.
        """
        super().SetFiringChainMode(n)
        groups = self._active_chain_groups()
        self.SetSkewFire(0 if groups == [0] else 1)


# Global phaser fire-range gate. Reconstructed from disassembly:
# Appc.dll exposes PhaserBank_GetMaxPhaserRange (sdk/.../App.py:11511) as
# a per-bank getter that nothing in the SDK ever sets — the engine fills
# it in internally from a single global ("phaser beam range normalisation"
# at 0x008E53DC). Player observation in stock BC (Galaxy class, HUD reading
# ~123 km when phasers still engaged) gives 700 GU = 122.5 km. Per-bank
# MaxDamageDistance (60.0 for Galaxy, 70.0 for Sovereign, etc.) controls
# damage falloff shape, not the firing gate.
PHASER_MAX_RANGE_GU = 700.0

# Tractor-beam engagement range.  BC's tractor emitters carry a per-bank
# MaxDamageDistance ≈ 118-120 GU (galaxy.py AftTractor2 = 118, vorcha = 120);
# unlike phasers there is no single engine-wide constant, so we gate the whole
# system on a representative 120 GU.  A target drifting past this drops the
# beam (the K1 tractor walk re-checks it every tick; the ENGAGE intent
# persists so the beam re-acquires when back in range). Its one home: pushed
# to the native kernel as a global (native_combat._globals).
#
# No other engagement gate: the target's shields do NOT matter. Measured on
# the original exe (stbc-oracle bible §7.5 R1, `tractor_engage_r20_noshields`
# against `tractor_engage_r20`): a Galaxy's projector locks a shielded target
# within one sample of StartFiring exactly as it does an unshielded one.
TRACTOR_MAX_RANGE_GU = 120.0




def _same_set(a, b) -> bool:
    """True iff `a` and `b` stand in the SAME set (identity). A setless
    object on either side shares a set with nothing. Interim weapon guard --
    see _target_within_range_gu."""
    from engine.systems import frames
    set_a = frames.containing_set(a)
    return set_a is not None and set_a is frames.containing_set(b)


def _target_within_range_gu(ship, target, max_range_gu: float) -> bool:
    """True iff `target` is within `max_range_gu` game units of `ship`.

    Shared fire-range gate for energy-weapon aggregators.  Legacy fixture
    support: if either object lacks GetWorldLocation, returns True so
    non-positional tests keep their previous behaviour.

    INTERIM GUARD (system-frames Plan 2, controller Ruling 5): a target whose
    containing set is not the SAME set as the firing ship's -- including a
    setless object on either side -- is out of range. The distance below is
    a raw set-local compare, meaningless across sets, and a cross-set beam is
    no longer drawn, so without this a bank could damage a ship in another
    set whose raw numbers happen to coincide. This is a stopgap until
    frame-aware weapon engagement lands (design spec §6 widening list); it
    makes a ship unable to phaser/tractor a target in a sibling region even
    when physically close. Same-set behaviour is unchanged.
    """
    if ship is None or target is None:
        return False
    if not hasattr(ship, "GetWorldLocation") or not hasattr(target, "GetWorldLocation"):
        return True
    if not _same_set(ship, target):
        return False
    sp = ship.GetWorldLocation()
    tp = target.GetWorldLocation()
    dx, dy, dz = tp.x - sp.x, tp.y - sp.y, tp.z - sp.z
    dist_sq = dx*dx + dy*dy + dz*dz
    return dist_sq <= max_range_gu * max_range_gu


class _HeldFireWeaponSystem(WeaponSystem):
    """Energy-emitter aggregator base (PhaserSystem, PulseWeaponSystem).

    Since the BC tick rewire the shared dispatch lives on WeaponSystem
    (StartFiring arms the tick, host_loop._pump_held_weapons runs native
    fire control's walk per tick).  This class only keeps the _can_engage
    fire-range hook (SingleFire moved to the WeaponSystem base — the
    property→system copy in ships.py hits every system type, and the
    hasattr guard there is always true through the _Stub, so torpedo
    systems were silently dropping their authored SetSingleFire).

    Subclasses override _can_engage(ship, target) to add a fire-range gate
    (phasers do; pulse weapons don't — a bolt's lifetime bounds its range).
    StartFiring consults it (no latch out of range) and the host_loop pump
    re-checks it per frame (held burst stops when the target drifts out).
    """

    def _can_engage(self, ship, target) -> bool:
        """Fire-range gate hook. Default: no gate. PhaserSystem overrides."""
        return True

    def StartFiring(self, target=None, offset=None) -> None:
        """No-target bail (regression guard): SDK FireWeapons dispatches
        pShip.GetTarget(), which is legitimately None (no target selected).
        Energy weapons (phaser/pulse/tractor) have nothing to aim/fire at
        with no target — latching _fire_held here left host_loop's per-frame
        damage loop stopping each bank (target is None) while the AI/UI
        re-called StartFiring every tick, producing a fire/stop flicker with
        SFX spam (and, for pulse weapons, real forward bolts with no
        target). Torpedo dumbfire is unaffected: it lives on the WeaponSystem
        base, which legitimately arms with target=None."""
        if target is None:
            return
        super().StartFiring(target=target, offset=offset)


class PhaserSystem(_HeldFireWeaponSystem):
    # Power-level constants from sdk/.../App.py:6444-6446 (three levels).
    # Values confirmed against the real BC engine (dev-console probe: HIGH=2,
    # LOW=0). PP_LOW is the "disable, don't destroy" mode — it deals no hull
    # damage, only subsystem damage (see combat.apply_hit `damage_hull`).
    PP_LOW = 0
    PP_MEDIUM = 1
    PP_HIGH = 2
    # K0 reads it to index PHASER_DISCHARGE_BY_POWER_LEVEL: mirrored only
    # while it is an index (native_combat.INDEX).
    _power_level = NativeField(native_combat.INDEX)

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._power_level = self.PP_HIGH
        self._aimed_weapon: int = 0

    def SetPowerLevel(self, level) -> None:
        # BC ships an uninitialized-stack-damage bug for out-of-range levels
        # (the audit's own recommendation is to clamp on write rather than
        # reproduce the corruption) — clamp to the three defined levels.
        self._power_level = max(0, min(2, int(level)))

    def GetPowerLevel(self) -> int:
        return self._power_level

    def GetAimedWeapon(self) -> int:                return self._aimed_weapon
    def SetAimedWeapon(self, v) -> None:            self._aimed_weapon = int(v)

    def _can_engage(self, ship, target) -> bool:
        return self._target_in_system_range(ship, target)

    def _target_in_system_range(self, ship, target) -> bool:
        """True iff `target` is within global phaser fire range
        (PHASER_MAX_RANGE_GU, ≈122.5 km — see module-level comment).

        BC's phaser fire-range gate is a single engine-wide constant,
        not per-bank: MaxDamageDistance scales damage falloff only.
        No charge drain, no beam, no SFX when the target is beyond
        the global range.

        Legacy fixture support: if either ship or target lacks
        GetWorldLocation, returns True so non-positional tests keep
        their previous behaviour.
        """
        return _target_within_range_gu(ship, target, PHASER_MAX_RANGE_GU)


class PulseWeaponSystem(_HeldFireWeaponSystem):
    """Pulse-weapon (disruptor/cannon) aggregator.

    Rides the shared BC tick (WeaponSystem.StartFiring arms, host_loop's
    pump runs native fire control's walk per tick).  Unlike PhaserSystem its emitters
    fire discrete projectile bolts and it keeps the base's no-op _can_engage
    (no fire-range gate — a bolt's lifetime bounds its range, so the only
    fire gates are arc + charge + cooldown).
    """
    pass


class TractorBeamSystem(_HeldFireWeaponSystem):
    """Tractor-beam aggregator.

    A tractor is a UI *toggle* (StartFiring = engage, StopFiring =
    toggle-off). Its fire decisions are the native K1 kernel's whole
    (fire control native only, M4; k1_fire_control.h, THE TRACTOR WALK):
    StartFiring records the ENGAGE intent (`_fire_held`) and runs the engage
    as a native session (native_combat.k1_tractor_start); every tick the
    held-weapon pump's tractor walk keeps the intent alive even when the beam
    cannot grip -- out of range or out of arc -- and re-acquires when the
    geometry allows, rotating through the projectors from
    `_next_emitter_index`. The hardpoints set SingleFire(1), so exactly one
    beam locks the target.

    A holding beam is never discharged; K0 drops it when its parent is off
    or starved (TractorBeam.UpdateCharge, k0_charging.cc). Each tick the
    native tractor force (tractor_force.h, engine.appc.tractor) applies the
    mode to the target. `_engage_state` caches the mode's engagement
    geometry (the captured HOLD world-point / TOW body-frame offset); it is
    invalidated on StopFiring and on any mode change.

    The methods below are the SDK's surface, thin over that native state.
    """
    # q10 ground truth (tools/probes/results/q10_battery_drain.txt): the tractor
    # is a DIRECT main-battery siphon — it bypasses the conduit budget and is
    # unscaled by the power slider (measured 600/s flat with sliders at 1.25).
    # This supersedes the spec's "tractor = conduit mode 0" decision; the manual
    # was right that it draws from Main, the RE doc's mode-1 (backup-first) row
    # is wrong-in-effect. The native pump branches on this flag (a steal, not a
    # conduit draw).
    # Mirrored (the native power piece's direct steal, subsystem_step.h THE
    # POWER PIECE): its own NativeClassDefault, never a plain attribute.
    DRAWS_DIRECT_FROM_MAIN = native_combat.NativeClassDefault(bool, True)

    # Tractor-beam mode constants from sdk/.../App.py:6774-6779.
    # SDK consumers: Preprocessors.py, AI/PlainAI/Warp.py, TowAway.py, etc.
    TBS_HOLD          = 0
    TBS_TOW           = 1
    TBS_PULL          = 2
    TBS_PUSH          = 3
    TBS_DOCK_STAGE_1  = 4
    TBS_DOCK_STAGE_2  = 5

    # Mirrored: what the K1 tractor walk and the tractor force read and write.
    _mode = NativeField(int)
    _was_firing = NativeField(bool)
    _next_emitter_index = NativeField(int)
    _engage_state = native_combat.EngageStateField()

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._mode = self.TBS_HOLD
        self._engage_state = None
        # Last observed IsFiring() value, for the ET_TRACTOR_BEAM_STARTED_/
        # STOPPED_FIRING edge-detect. Not derived from _fire_held: the beam
        # drops and re-acquires (range, arc) while the ENGAGE intent is
        # continuously held, and each crossing is a transition BC's
        # PowerDisplay repaints for.
        self._was_firing = False
        self._next_emitter_index = 0

    def _wants_power(self) -> bool:
        """The tractor siphons power only while a beam is actually held (a
        powered-but-idle tractor draws nothing — PowerDisplay's siphon
        semantics).  The draw is a DIRECT main-battery steal (DRAWS_DIRECT_FROM_MAIN,
        q10); the gate here is the firing state, not the alert-driven on/off flag."""
        return bool(self.IsOn()) and self._any_child_firing()

    def _any_child_firing(self) -> bool:
        """True if any child tractor-beam emitter is currently firing.  Same
        child-weapon walk PowerDisplay.HandleTractor uses."""
        for i in range(self.GetNumWeapons()):
            em = self.GetWeapon(i)
            if em is not None and em.IsFiring():
                return True
        return False

    def GetMode(self) -> int:
        return self._mode

    def SetMode(self, mode) -> None:
        new_mode = int(mode)
        if new_mode != self._mode:
            # A mode switch invalidates any captured engagement geometry
            # (e.g. HOLD's pinned world-point or TOW's body-frame offset).
            self._engage_state = None
        self._mode = new_mode

    def IsTryingToFire(self) -> int:
        return self.IsFiring()

    def IsEngaged(self) -> int:
        """The persistent toggle *intent*, independent of the instantaneous
        IsFiring() beam state.  The HUD / F2 menu tractor toggle reflects THIS:
        while engaged the beam auto-fires whenever the target is in range (and
        re-acquires each tick in the K1 tractor walk), so the button stays "On"
        even if the beam momentarily isn't gripping."""
        return 1 if self._fire_held else 0

    def StartFiring(self, target=None, offset=None) -> None:
        """The gates, then the native engage (native_combat.k1_tractor_start:
        the ENGAGE intent is recorded BEFORE the engage-range check, so the
        pump re-acquires when the geometry allows)."""
        if not self.IsOn() or target is None:
            return
        if _is_offline(self):
            return
        if _cloak_blocks_fire(self):
            return
        if _dewarp_blocks_fire(self):
            return
        native_combat.k1_tractor_start(self, target, offset)

    def IsFiring(self) -> int:
        """Instantaneous BEAM state only — deliberately NOT OR'd with
        `_fire_held` like the base: the engaged-but-not-gripping intent is
        surfaced separately via IsEngaged() (the HUD toggle reads that)."""
        return 1 if self._any_child_firing() else 0

    def _sync_firing_event(self) -> None:
        """Queue ET_TRACTOR_BEAM_STARTED_/STOPPED_FIRING on a beam transition
        (gaps #8/#9 in docs/reference/engine/event-emitter-gaps.md; an
        effect-queue entry, ruling R8, delivered at the next flush). The
        Python twin of the K1 tractor walk's sync (k1_fire_control.cc
        tractor_sync), for StopFiring: change both. A no-op unless the
        state actually crossed.

        Destination is the parent SHIP, not the system:
        Bridge/PowerDisplay.py:1013 casts GetDestination() to ShipClass and
        then walks the ship's own tractor system, and
        Conditions/ConditionFiringTractorBeam.py:26-27 registers broadcast
        METHOD handlers filtered to the watched ship -- that filter compares
        against the event's destination. Neither event carries a payload:
        both handlers re-read the live state themselves.
        """
        now = bool(self.IsFiring())
        if now == self._was_firing:
            return
        ship = self.GetParentShip()
        if ship is None:
            # Don't mark the transition consumed: a parentless system has
            # nowhere to send the event, but the NEXT sync (once it has a
            # parent) must still see the crossing rather than finding
            # _was_firing already flipped and treating it as a non-event.
            return
        self._was_firing = now
        effect_queue.emit(effect_queue.TRACTOR_STARTED if now
                          else effect_queue.TRACTOR_STOPPED, self, ship)

    def StopFiring(self, *args) -> None:
        # The K1 tractor walk's stop (k1_fire_control.cc tractor_stop) logs
        # these writes itself: change both.
        self._engage_state = None
        super().StopFiring(*args)
        self._sync_firing_event()


class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual phaser emitter under a parent PhaserSystem
    (WeaponSystemProperty WST_PHASER).  Charge fields populated by Pass 4
    from the parent PhaserProperty (galaxy.py:209-214 for typical values).
    Inherits CanFire/StopFiring/UpdateCharge from the mixin; Fire wraps the
    mixin's implementation to post ET_WEAPON_FIRED (Task 10).
    """
    REMOTE_FIRE_PRIORITY = REMOTE_PHASER_PRIORITY   # 0.6; pulse/tractor stay 0.5

    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def _discharge_rate_per_second(self) -> float:
        """BC's phaser drain is the power-level TABLE on the owning
        PhaserSystem, not the hardpoint's NormalDischargeRate (which the
        phaser path never reads — every stock emitter authors 1.0, so the
        two were indistinguishable until CGSovereign authored 200.0 and
        emptied its tank in one tick).  A bank always hangs under a
        PhaserSystem in BC; the MED fallback is defensive only."""
        parent = self.GetParentSubsystem()
        level = parent.GetPowerLevel() if hasattr(parent, "GetPowerLevel") else 1
        try:
            return PHASER_DISCHARGE_BY_POWER_LEVEL[level]
        except (IndexError, TypeError):
            return 0.0      # BC's default arm for an out-of-range level

    # Fire is the mixin's (decide, then effect). The decision's was_firing
    # is the value read before CanFire, which never writes _firing.

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level

    def GetChargePercentage(self) -> float:
        """0.0 when the parent system is off or this bank is disabled
        (Task 10, audited §1.6/§7.4) — otherwise the WeaponsDisplay would
        keep showing a charge bar for a bank that cannot fire."""
        if self._max_charge <= 0.0:
            return 0.0
        parent = self.GetParentSubsystem()
        if parent is not None and not parent.IsOn():
            return 0.0
        if self.IsDisabled():
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v

    def CanHit(self, target_world_point) -> int:
        """1 if `target_world_point` lies inside this bank's firing arc and
        within its maximum range, else 0.

        The sole Python caller is Conditions/ConditionInPhaserFiringArc.py:175
        (`pBank.CanHit(vTargetLocation)`), reached from AI/Compound/FedAttack.py
        and AI/Setup.py.

        Must return a REAL int. Undefined, this resolved to a truthy
        `_Stub` via TGObject.__getattr__, so the condition reported every
        target as in-arc and FedAttack fired with no arc discipline at all.
        The gap was latent rather than observed — `CanHit` never appears in
        docs/stub_heatmap.md, so the path did not execute in 201 recorded runs.

        Range semantics: MaxDamageDistance == 0 means UNBOUNDED, not
        unreachable. Most hardpoints omit the field, and reading 0 as a
        zero-radius limit would silently disable every such bank.
        """
        if not isinstance(target_world_point, TGPoint3):
            return 0
        ship = self.GetParentShip()
        origin = subsystem_world_position(self, ship)
        if origin is None:
            return 0

        dx = target_world_point.x - origin.x
        dy = target_world_point.y - origin.y
        dz = target_world_point.z - origin.z
        dist = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist <= 0.0:
            return 0

        max_range = 0.0
        prop = self.GetProperty() if hasattr(self, "GetProperty") else None
        if prop is not None and hasattr(prop, "GetMaxDamageDistance"):
            try:
                max_range = float(prop.GetMaxDamageDistance())
            except Exception:
                max_range = 0.0
        if max_range > 0.0 and dist > max_range:
            return 0

        aim = TGPoint3(dx / dist, dy / dist, dz / dist)
        return 1 if _emitter_in_arc(self, ship, aim) else 0


class PulseWeapon(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual pulse-weapon emitter under a parent PulseWeaponSystem
    (WeaponSystemProperty WST_PULSE).  Energy-weapon charge surface plus
    per-shot cooldown timer; see ships/Hardpoints/vorcha.py for SetCooldownTime
    call sites.  Inherits Fire/CanFire/StopFiring/UpdateCharge from the mixin.
    """
    # UpdateCharge also counts the cooldown down and drives the charge
    # watcher every tick, so a pulse weapon sleeps only once the cooldown is
    # spent. The watcher's update while asleep re-sends the fraction it
    # already holds (nothing a sleeper reads has been written), so no range
    # check can cross; the audit snapshots the watcher to prove it.
    _cooldown_remaining = NativeWakeField(float)
    _cooldown_time = NativeField(float)
    # The charge watcher's check count (K0 runs the watcher's Python only
    # when it has checks). The watcher keeps it: every AddRangeCheck /
    # RemoveRangeCheck writes it back onto its owner (FloatRangeWatcher).
    _watch_checks = NativeField(int)
    # Assigning a watcher (construction, or a later replacement) re-derives
    # _watch_checks from it (native_combat.ChargeWatcherField).
    _charge_watcher = native_combat.ChargeWatcherField()
    _passive_audit_children = ("_charge_watcher",)
    # K1's native launch reads the cannon's DamageRadiusFactor override
    # (written by ShipSubsystem's property copy), as a tube's.
    _damage_radius_factor = NativeField(float)

    def _passive_at_rest(self) -> bool:
        return (_EnergyWeaponFireMixin._passive_at_rest(self)
                and self._cooldown_remaining <= 0.0)

    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None
        self._cooldown_time: float = 0.0
        # Per-shot cooldown countdown. Set to GetCooldownTime() at Fire,
        # decremented in UpdateCharge; gates CanFire while > 0.
        self._cooldown_remaining: float = 0.0
        # FloatRangeWatcher handed to Conditions/ConditionPulseReady.py:163
        # (GetChargeWatcher()); watches the charge FRACTION (charge / max_charge)
        # so the condition's MinFiringCharge/MaxCharge threshold lines up.
        # Its owner back-reference keeps _watch_checks equal to its checks.
        self._watch_checks: int = 0
        self._charge_watcher = FloatRangeWatcher(owner=self)

    def SetProperty(self, prop) -> None:
        super().SetProperty(prop)
        # The projectile module is named by the property: resolve it for the
        # native mirror now (no-op with the switch off).
        native_combat.push_pulse_params(self)

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level
    def GetCooldownTime(self) -> float:             return self._cooldown_time

    def GetLaunchSpeed(self) -> float:
        """SDK AI/Preprocessors.py:778 (FireScript.GetWeaponInfo) — used to
        lead the AI's aim point on pulse-weapon fire (fTime = fDistance /
        fSpeed, Preprocessors.py:742). There is no authored per-weapon
        launch-speed field; the real value lives on the bound projectile
        module (e.g. Tactical/Projectiles/PulseDisruptor.py:43
        GetLaunchSpeed() -> 55.0), the launch speed native fire control's
        cannon launch uses (pulse_module_params). Resolve it
        the same way: PulseWeaponProperty.GetModuleName() names the
        projectile script; import it and read its GetLaunchSpeed(). Returns
        0.0 (not a hardcoded default) if the property, module name, module,
        or attribute is genuinely absent — matching pulse_module_params'
        missing-attribute reading rather than inventing a number."""
        prop = self.GetProperty()
        script = prop.GetModuleName() if (prop is not None and hasattr(prop, "GetModuleName")) else ""
        if not script:
            return 0.0
        import importlib
        try:
            mod = importlib.import_module(script)
        except ImportError:
            return 0.0
        return float(mod.GetLaunchSpeed()) if hasattr(mod, "GetLaunchSpeed") else 0.0

    def GetChargeWatcher(self):
        """FloatRangeWatcher on the charge FRACTION
        (Conditions/ConditionPulseReady.py:163)."""
        return self._charge_watcher

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v

    # ── Discrete-shot firing (overrides the beam mixin behaviour) ───────────
    # Pulse cannons fire projectile bolts, not held beams: Fire spawns one
    # bolt, dumps accumulated charge, and starts a per-shot cooldown. There
    # is no looping SFX and _firing never stays True — so the mixin's
    # CanFire always takes the ">= MinFiringCharge" branch (never the
    # ">0 sustain" branch, since _firing is always False here) and
    # UpdateCharge always takes the RECHARGE branch (see below). Re-arm is
    # therefore already "at exactly MinFiringCharge, no headroom" (Task 10,
    # audited §1.6) — the per-shot cooldown (SetCooldownTime, BoP 0.2s) is
    # the anti-flutter mechanism, not charge hysteresis.

    def GetDamageScale(self) -> float:
        """PulseWeapon_GetDamageScale (0x00619400 → 0x00575270): the bolt
        damage multiplier for this emitter's power setting — 0.2 / 0.5 / 1.0.
        K1's native launch reads it from the pushed table
        (fire_gates.cc, pulse_damage_scale): change both."""
        return PULSE_DAMAGE_SCALE_BY_POWER_SETTING[self._power_setting]

    def _shot_cost(self) -> float:
        """Charge one bolt costs: NormalDischargeRate × the power-setting
        scale (BC's GetPowerScaled) — 0.5 / 1.0 / 2.0 on a stock cannon.
        K1 computes it (fire_gates.cc, shot_cost): change both."""
        return (self._normal_discharge_rate
                * PULSE_COST_SCALE_BY_POWER_SETTING[self._power_setting])

    def CanFire(self) -> int:
        """The native rule (fire_gates.cc can_fire: the cooldown, then the
        mixin's gates with affordability for charge; M8.6)."""
        return native_combat.k1_can_fire(self)

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when a bolt launched -- a discrete shooter reports
        IsFiring() False right after a successful shot, so the explicit bool
        is the answer. A one-weapon native session (native_combat.k1_fire,
        M8.6): CanFire, the stamps, the lead solve and the arc, then the
        bolt's SPAWN, the drain and the cooldown (k1_fire_control.h)."""
        return native_combat.k1_fire(self, target, offset)

    def UpdateCharge(self, dt: float) -> None:
        if self._cooldown_remaining > 0.0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - dt)
        # _firing stays False for pulse weapons, so the mixin takes the
        # RECHARGE branch; CanFire re-arms at exactly MinFiringCharge (no
        # headroom — see the class docstring above).
        _EnergyWeaponFireMixin.UpdateCharge(self, dt)
        # Drive the charge watcher with the charge FRACTION so
        # Conditions/ConditionPulseReady.py fires its ET_CHARGE_TOGGLE
        # crossing event (guard divide-by-zero → 0.0). K0 stands in for
        # this line on an owned watcher (k0_charging.h, THE EFFECT QUEUE:
        # the value committed, WATCH queued): change both together.
        self._charge_watcher._update(self.GetChargePercentage())

    def StopFiring(self) -> None:
        # Discrete weapon — no _loop_handle to silence; just clear target refs.
        # K1 (a cannon its walk stops) and K0 (one drained dry) log these
        # writes themselves, from stop_firing.h: change both together.
        self._firing = False
        self._target = None
        self._target_offset = None


class TractorBeam(_EnergyWeaponFireMixin, WeaponSystem):
    """Individual tractor-beam emitter under a parent TractorBeamSystem
    (WeaponSystemProperty WST_TRACTOR).  Same energy-weapon charge model
    as phasers; see galaxy.py:853-854 for typical values (aft tractors
    recharge=0.5, forward tractors 0.3).  Inherits Fire/CanFire/StopFiring/
    UpdateCharge from the mixin.
    """
    def __init__(self, name: str = ""):
        super().__init__(name)
        _init_energy_weapon_state(self)
        self._firing: bool = False
        self._target = None
        self._target_offset = None

    def GetMaxCharge(self) -> float:                return self._max_charge
    def GetMinFiringCharge(self) -> float:          return self._min_firing_charge
    def GetNormalDischargeRate(self) -> float:      return self._normal_discharge_rate
    def GetRechargeRate(self) -> float:             return self._recharge_rate
    def GetChargeLevel(self) -> float:              return self._charge_level

    def GetChargePercentage(self) -> float:
        if self._max_charge <= 0.0:
            return 0.0
        return self._charge_level / self._max_charge

    def SetChargeLevel(self, v) -> None:
        v = float(v)
        if v < 0.0:                self._charge_level = 0.0
        elif v > self._max_charge: self._charge_level = self._max_charge
        else:                      self._charge_level = v

    def UpdateCharge(self, dt: float) -> None:
        """Sustained-hold charge model — overrides the phaser/pulse
        discharge-to-zero auto-stop.

        A tractor holds CONTINUOUSLY while engaged (you can pin a ship
        indefinitely) and its charge does not move while it does: measured
        on the original exe, a Galaxy projector holding a target reads 5.00
        for the whole run (stbc-oracle bible §7.5 R1, `tractor_*`), so the
        hardpoint's NormalDischargeRate is not a hold cost. The beam is
        gated by parent power only — if the line goes down it drops. When
        idle we fall back to the mixin's normal condition-scaled recharge.

        This used to drain toward MinFiringCharge while holding; that was a
        design choice with no capture behind it.
        """
        if self._firing:
            parent = self.GetParentSubsystem()
            if parent is None or not parent.IsOn():
                # Power loss stops the beam (routes through StopFiring so the
                # looped SFX handle is silenced).
                self.StopFiring()
                return
            # Power starvation: the parent system draws through PowerSubsystem's
            # consumer model now (Task 4); when the grid can't feed the tractor
            # its efficiency collapses to zero while it still wants power, so the
            # beam drops (replaces the old per-tick StealPower gate).
            if (hasattr(parent, "GetPowerPercentage")
                    and parent.GetPowerPercentage() <= 0.0
                    and parent.GetNormalPowerWanted() > 0.0):
                self.StopFiring()
                return
            # No discharge while holding — charge is untouched.
            return
        # Idle fall-through note: an idle TractorBeamSystem doesn't want power
        # (_wants_power False -> factor zeroed by the pump), so the mixin's
        # factor-scaled recharge is 0 while idle. Harmless: holding never
        # drains, so there is nothing to recharge.
        super().UpdateCharge(dt)


# ── Torpedo fire gates (Task 7, audited) ────────────────────────────────────
# BC's targeted torpedo fire resolves a static aim point (no lead/intercept)
# and rejects it outside a square +/-30 degree cone about the tube's authored
# Direction, checked yaw and pitch INDEPENDENTLY.  Neither step touches the
# launch trajectory itself (that stays BC-faithful per Task 6: straight out
# the tube's Direction, aim never steers the shot) -- they are pure FIRE
# gates: fail either and the tube posts ET_WEAPON_FIRE_FAILED and does not
# launch at all.

_TORPEDO_CONE_HALF_ANGLE = 0.5235984   # BC's literal, NOT math.radians(30)


class TorpedoTube(Weapon):
    """Individual launcher under a parent TorpedoSystem.  Ammo-type tracking
    lives on the parent's slot table; this class owns per-tube reload state.

    Reload model recovered from stbc.exe
    (docs/reference/gameplay/combat-and-damage.md:740-830):
    reload state is a per-slot timer array, one slot per MaxReady, driven by
    the GAME clock (not wall time, so a paused sim makes no reload progress).
    ImmediateDelay is a CanFire refire gate (gameTime - last_fire_time >=
    ImmediateDelay), not a fire-to-launch latency. ReloadDelay is the per-slot
    cooldown after firing.
    """
    # Passive state (engine/appc/passive_weapons.py): a fully loaded tube
    # sleeps out of the weapons walk until a launch, a Set/Inc/DecNumReady,
    # an unload or a MaxReady change writes one of these.
    _num_ready = NativeWakeField(int)
    _max_ready = NativeWakeField(int)
    # Mirrored into the native combat row on every write (native_combat).
    _last_fire_time = NativeField(float)
    _immediate_delay = NativeField(float)
    _skew_fire = NativeField(bool)
    # K0 (the charging kernel) reads the reload delay and the per-slot lists.
    # The lists are mostly written IN PLACE (list[i] = v), which no
    # descriptor sees: every such writer calls _push_slots after mutating
    # (_start_slot_cooldown, _sync_slots_to_num_ready, UpdateReload,
    # ReloadTorpedo); a rebind (_resize_slots) pushes by itself.
    _reload_delay = NativeField(float)
    _reload_timers = NativeFloatList()
    _reload_advanced_at = NativeFloatList()
    # K1's native launch reads the launcher's DamageRadiusFactor override
    # (written by ShipSubsystem's property copy).
    _damage_radius_factor = NativeField(float)

    def _passive_at_rest(self) -> bool:
        """True when UpdateReload, run now, would return at its
        `num_ready >= max_ready` test. The _ensure_slots() before that test
        is a no-op too: the step that put the tube to sleep just ran it, and
        the slot arrays only change length with _max_ready."""
        return self._num_ready >= self._max_ready

    def _passive_on_sleep(self) -> None:
        passive_weapons.on_sleep(self)

    def _passive_on_wake(self) -> None:
        passive_weapons.on_wake(self)

    def __init__(self, name: str = ""):
        super().__init__(name)          # Weapon.__init__ seeds _firing/_target
        self._num_ready: int = 0
        # GAME time. BC inits to -1000.0 (combat-and-damage.md:757) so a fresh
        # tube already satisfies the ImmediateDelay gate. NOT -inf: -inf poisons
        # any subtraction a caller might do on GetLastFireTime().
        self._last_fire_time: float = -1000.0
        self._immediate_delay: float = 0.0
        self._reload_delay: float = 0.0
        self._max_ready: int = 0
        # One slot per MaxReady. Value = ACCUMULATED reload progress in game-seconds
        # (BC's per-slot timer at TorpedoTube+0xAC, counting UP toward ReloadDelay);
        # _SLOT_LOADED (-1.0) = ready. This is an INTEGRATOR, not a start stamp:
        # UpdateReload advances each cooling slot by factor x elapsed game time, so
        # progress banked at one power level survives a later power change
        # (weapon-firing-mechanics.md §2.6). _reload_advanced_at[i] holds the game
        # time slot i was last advanced, so each call credits only the interval
        # since the previous one — the game-clock delta, never the passed render dt.
        self._reload_timers: list[float] = []
        self._reload_advanced_at: list[float] = []
        # Skew-fire flag — persistent across firing, set by TorpedoSystem or mission.
        self._skew_fire: bool = False

    def _resize_slots(self) -> None:
        """(Re)build the per-slot reload arrays to MaxReady, all slots loaded.
        Called by ships.py after the hardpoint property is copied in.
        The progress array and its parallel last-advanced-at array are always
        rebuilt together so they never desync in length."""
        n = max(0, int(self._max_ready))
        self._reload_timers = [_SLOT_LOADED] * n
        self._reload_advanced_at = [0.0] * n

    def _ensure_slots(self) -> None:
        """Self-heal: rebuild _reload_timers if it has desynced from
        _max_ready. Production always calls _resize_slots() from
        ships.py:_copy_torpedo_tube_fields, but _max_ready is real SDK/test
        surface that can be set directly (six unit-test fixtures do exactly
        that) — without this, a tube that fires would stamp NO slot and
        UpdateReload would find nothing cooling, bricking the tube forever
        with no exception raised.  Called at the top of every method that
        reads or writes _reload_timers."""
        if (len(self._reload_timers) != self._max_ready
                or len(self._reload_advanced_at) != self._max_ready):
            self._resize_slots()

    def _start_slot_cooldown(self, now: float) -> None:
        """Put one loaded slot into cooldown: zero progress, advance-clock at `now`.

        A cooling slot's timer counts UP from 0.0; seeding the last-advanced-at
        stamp to `now` means its FIRST UpdateReload call credits only the interval
        since firing, not the whole game clock.

        K1 logs a native launch's call as slot writes (k1_fire_control.cc,
        plan_launch / log_launch): change both."""
        self._ensure_slots()
        for i in range(len(self._reload_timers)):
            if self._reload_timers[i] == _SLOT_LOADED:
                self._reload_timers[i] = 0.0
                self._reload_advanced_at[i] = now
                if native_combat._enabled:
                    self._push_slots()
                return

    def _push_slots(self) -> None:
        """Both slot lists were written in place: push them to the native
        combat mirror (callers test native_combat._enabled first, so the
        switch-off path pays one module attribute read)."""
        native_combat.push_field(self, "_reload_timers")
        native_combat.push_field(self, "_reload_advanced_at")

    def _sync_slots_to_num_ready(self) -> None:
        """Keep _reload_timers consistent after a direct _num_ready mutation.

        SetNumReady/IncNumReady/DecNumReady are real SDK surface (App.py:
        6018-6020) — a mission can call them directly, bypassing Fire/
        ReloadTorpedo.  Without this, the slot array and _num_ready silently
        disagree: e.g. SetNumReady(0) left every slot LOADED, so UpdateReload
        found nothing cooling and the tube never refilled.

        Demotes/promotes the minimum number of slots needed to make exactly
        `_num_ready` (clamped to the slot count) read LOADED: demoted slots
        start cooling from now (zero progress); promotion prefers the slot that
        has been cooling longest (LARGEST accumulated progress), matching
        ReloadTorpedo's own "oldest cooling slot wins" rule."""
        self._ensure_slots()
        target = max(0, min(int(self._num_ready), len(self._reload_timers)))
        loaded_idx = [i for i, t in enumerate(self._reload_timers) if t == _SLOT_LOADED]
        cooling_idx = [i for i, t in enumerate(self._reload_timers) if t != _SLOT_LOADED]
        if len(loaded_idx) > target:
            now = _game_time()
            for i in loaded_idx[target:]:
                self._reload_timers[i] = 0.0
                self._reload_advanced_at[i] = now
            if native_combat._enabled:
                self._push_slots()
        elif len(loaded_idx) < target:
            # Most-progressed (largest timer) = cooling longest = promote first.
            cooling_idx.sort(key=lambda i: self._reload_timers[i], reverse=True)
            need = target - len(loaded_idx)
            for i in cooling_idx[:need]:
                self._reload_timers[i] = _SLOT_LOADED
            if native_combat._enabled:
                native_combat.push_field(self, "_reload_timers")

    def GetNumReady(self) -> int:                   return self._num_ready

    def _clamp_num_ready(self, v) -> None:
        """_num_ready must never exceed MaxReady, or fall below zero.

        These three setters are real SDK surface (App.py:6018-6020), so a
        mission can drive them directly.  Unclamped, _num_ready ran ahead of the
        slot array and _sync_slots_to_num_ready only clamped its own TARGET, not
        the field — so a 1-slot tube told SetNumReady(5) would launch FOUR
        torpedoes (Fire kept decrementing and spawning while
        _start_slot_cooldown found no loaded slot and silently no-op'd), and
        then never reload again (UpdateReload's `num_ready >= max_ready` guard
        held forever).  Neither failure raised.
        """
        self._num_ready = max(0, min(int(v), int(self._max_ready)))
        self._sync_slots_to_num_ready()

    def SetNumReady(self, v) -> None:
        self._clamp_num_ready(v)

    def IncNumReady(self) -> None:
        self._clamp_num_ready(self._num_ready + 1)

    def DecNumReady(self) -> None:
        self._clamp_num_ready(self._num_ready - 1)

    def GetLastFireTime(self) -> float:             return self._last_fire_time
    def SetLastFireTime(self, v) -> None:           self._last_fire_time = float(v)
    def GetImmediateDelay(self) -> float:           return self._immediate_delay
    def GetReloadDelay(self) -> float:              return self._reload_delay
    def GetMaxReady(self) -> int:                   return self._max_ready

    def _parent_ammo(self):
        """The parent TorpedoSystem's currently-selected ammo type, or None
        if there is no parent or no ammo type is configured.
        GetParentSubsystem() is always the TorpedoSystem this tube was
        AddChildSubsystem'd under."""
        parent = self.GetParentSubsystem()
        if parent is None:
            return None
        return parent.GetCurrentAmmoType()

    def _rounds_loaded_systemwide(self) -> int:
        """System-wide count of rounds currently chambered across ALL of the
        parent system's tubes — BC's TorpedoSystem+0x118 (NumReady), the value
        the reload gate compares stores against (weapon-firing-mechanics.md §2.2).

        Computed on demand from the live per-tube counts rather than kept as a
        stored counter, so it can never desync (the per-tube _num_ready already
        needs a self-heal/sync layer; a second incrementally-maintained counter
        would invite the same class of bug).  BC's +0x118 is a single all-types
        count; summing every tube's NumReady matches it, since our tubes fire the
        parent's currently-selected type and carry no per-tube ammo-type of their
        own.  Falls back to this tube's own count if it has no parent."""
        parent = self.GetParentSubsystem()
        if parent is None:
            return self._num_ready
        total = 0
        for c in getattr(parent, "_children", ()):
            if isinstance(c, TorpedoTube):
                total += c.GetNumReady()
        return total

    def _reload_denied_by_ammo(self) -> bool:
        """The ReloadTorpedo gate (BC weapon-firing-mechanics.md §2.2, gate 2):
        reload iff ``AmmoCounts > NumReady`` — a round of the current type exists
        in inventory that is NOT already sitting in a tube.  Deny when it does
        not, i.e. ``GetAvailable() <= rounds-loaded-system-wide``.

        Because we debit ammo at FIRE (not at reload), GetAvailable() is the
        TOTAL inventory of the type — it still counts chambered-but-unfired
        rounds, exactly like BC's AmmoCounts.  Checking only ``<= 0`` (as an
        earlier gate did here) let a second empty tube re-chamber a round
        already loaded in another tube, so firing both over-issued.  Finite types
        only; unlimited/undeclared ammo never gates."""
        ammo = self._parent_ammo()
        finite = ammo is not None and not getattr(ammo, "_unlimited", True)
        if not finite:
            return False
        return ammo.GetAvailable() <= self._rounds_loaded_systemwide()

    def CanFire(self) -> int:
        """BC torpedo CanFire (combat-and-damage.md:822-826):
        powered AND num_ready > 0 AND the SHIP-WIDE 0.5s stagger has expired
        AND this tube is not itself disabled (spec §3.3 audited gate 2) AND
        the ImmediateDelay refire gate has expired AND ammo is available.

        ImmediateDelay is a REFIRE GATE, not a fire->launch latency: it prevents
        rapid double-fires. Hardpoint values run 0.25s (galaxy) to 5.0s.
        The volley-level ammo reserve gate also lives on the parent
        TorpedoSystem.StartFiring; this per-tube check additionally covers
        direct CanFire() callers that bypass StartFiring.

        The stagger gate (Task 7, audited) throttles the WHOLE SYSTEM to one
        launch per 0.5s of game time: a single tap that would otherwise fire
        every ready tube in the working group in the same tick now only
        launches the first one (it stamps parent._last_system_fire_time; the
        rest fail this gate within the same tick since gameTime delta is 0).
        Skew-fire tubes are exempt — they're the deliberately-desynced spread
        pattern, not the ship-wide volley.

        The native rule (fire_gates.cc can_fire, M8.6): fire control has no
        Python copy (M3).
        """
        return native_combat.k1_can_fire(self)

    def Fire(self, target=None, offset=None) -> bool:
        """Returns True when a torpedo launched -- discrete shooter, so the
        explicit bool is the answer.

        Task 7 audited gates, applied AFTER CanFire (power/stagger/reload/
        ammo) passes:

          * targeted path (``target`` is not None): resolve the static aim
            point (no lead -- Task 7 audited), then the +/-30 degree square
            cone about the tube's Direction.  Either failure posts
            ET_WEAPON_FIRE_FAILED and returns False WITHOUT consuming a
            round or starting the stagger/reload cooldown -- a rejected shot
            never fires.  Only on success does this stamp ``_target``/
            ``_target_offset`` -- "Fire stamps the homing state"; a
            dumb call (target=None) never does, so the torpedo homes on
            nothing.
          * dumb path (``target`` is None): straight to the launch, no aim
            resolve, no cone -- matches BC (FireDumb has no target to gate).

        A one-weapon native session (native_combat.k1_fire, M8.6; the launch
        at the boundary, k1_fire_control.h LAUNCHES AT THE BOUNDARY).
        """
        return native_combat.k1_fire(self, target, offset)

    def _broadcast_weapon_fired(self, target) -> None:
        """Post ET_WEAPON_FIRED: Source = the TUBE, Destination = the owning
        ship.  Posted AFTER ET_TORPEDO_FIRED on every successful launch
        (weapon-firing-mechanics.md §1.5/§2.4, audited).  Delegates to the
        module-level ``_post_weapon_fired`` shared with PhaserBank.Fire
        (Task 10)."""
        _post_weapon_fired(self, target)

    def _broadcast_weapon_fire_failed(self) -> None:
        """Post ET_WEAPON_FIRE_FAILED: Destination = the TUBE.  Posted when a
        targeted fire fails the aim-point resolve or the +/-30 degree cone.

        ⚠️ ``ET_WEAPON_FIRE_FAILED`` IS ``ET_CANT_FIRE`` — both are 0x800037
        (events.py:70-72 keeps the descriptive name as an alias so the two can
        never drift).  The older claim here that "no shipped SDK script
        listens" is FALSE and has been since the constant sweep made 0x800037
        real: Bridge/TacticalMenuHandlers.py:422 and
        Bridge/TacticalCharacterHandlers.py:58 both register ``PlayerCantFire``
        for it.

        Neither reaches this post, for two independent reasons, and BOTH are
        load-bearing — do not "tidy" either away: they are registered on the
        PLAYER instance while this addresses the TUBE, and this post sets no
        Source at all, so a ``PlayerCantFire``-shaped consumer would evaluate
        ``TorpedoSystem_Cast(None)``.  That divergence from the sibling
        emitters (which all pair Source = the emitting object with Destination
        = whatever the handler casts or filters on) is why this one is inert.
        If this event ever needs a real consumer, give it a Source and decide
        its destination deliberately rather than inheriting this shape.

        Inside the effect queue's scope it is queued (WEAPON_FIRE_FAILED)."""
        if effect_queue.deferring():
            effect_queue.post(effect_queue.WEAPON_FIRE_FAILED, self)
            return
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_WEAPON_FIRE_FAILED)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_WEAPON_FIRE_FAILED broadcast", _e)

    def _broadcast_ammo_consumed_if_player(self) -> None:
        """Post ET_TORPEDO_AMMO_CONSUMED, but ONLY when the firing ship is
        the player ship (BC locality gate — audited).  Source = the TUBE,
        Destination = the ship, mirroring ET_WEAPON_FIRED.  Inside the
        effect queue's scope it is queued (AMMO_CONSUMED), the gate read at
        delivery."""
        if effect_queue.deferring():
            effect_queue.post(effect_queue.AMMO_CONSUMED, self)
            return
        ship = self._climb_to_ship()
        import App
        try:
            if ship is None or ship is not App.Game_GetCurrentPlayer():
                return
        except Exception:
            return
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_AMMO_CONSUMED)
            evt.SetSource(self)
            evt.SetDestination(ship)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_AMMO_CONSUMED broadcast", _e)

    # FireDumb is inherited from Weapon — it was a byte-identical duplicate here,
    # and keeping the override would have skipped the base's new CanFire() gate.

    def UpdateReload(self, dt: float = 0.0) -> None:
        """Integrate each cooling slot's reload progress; reload one when it
        reaches ReloadDelay.

        BC (weapon-firing-mechanics.md §2.6): TorpedoTube::Update advances every
        charging slot by ``NormalPowerPercentage x dt`` per tick and reloads when
        the timer exceeds ReloadDelay. It is an INTEGRATOR — progress banked at one
        power level is never re-valued when power later changes. The prior
        start-stamp + ``reload_delay / factor`` scheme retroactively rescaled the
        WHOLE elapsed interval against the current factor on every call, so a
        mid-reload power change snapped a nearly-loaded tube back toward empty
        (drop) or finished it far too early (rise).

        `dt` is accepted for call-site compatibility (host_loop._advance_weapons)
        and DELIBERATELY IGNORED. _advance_weapons runs once per RENDER frame with
        a constant TICK_DT = 1/60 (host_loop.py:6054, :5525) — it is NOT inside the
        fixed-timestep sim loop, so the passed dt is a lie (a fixed 1/60, not the
        real frame delta). Integrating it would make reload frame-rate dependent:
        a Galaxy tube would reload in 20 s on a 120 Hz display. Instead each slot
        advances by ``factor x (now - _reload_advanced_at[slot])`` — the GAME-CLOCK
        delta since that slot was last advanced — which is frame-rate independent
        (the game clock ticks at a fixed rate regardless of render cadence) AND
        banks progress across a power change. This is BC's per-tick integral
        re-expressed for our variable render-frame cadence.

        Power throttles the reload: a half-powered torpedo system reloads at half
        rate. An unpowered (factor <= 0) system makes no progress, but the
        advance-clock still moves forward so the unpowered interval is never
        retroactively banked once power returns.
        """
        self._ensure_slots()
        if self._num_ready >= self._max_ready:
            return
        parent = self.GetParentSubsystem()
        factor = (parent.GetNormalPowerPercentage()
                  if parent is not None else 1.0)
        # isinstance guard: a missing GetNormalPowerPercentage hands back a truthy
        # _Stub (TGObject.__getattr__), and _Stub comparisons don't behave like
        # numbers. Coerce anything non-numeric or negative to 0.0 — no power, no
        # progress. NOTE we no longer early-return here: the advance-clock below
        # must still move forward at factor 0 so a later power-up doesn't credit
        # the unpowered gap (the old code's `40.0 / _Stub == 0.0` divisor made a
        # zero delay reload EVERY frame — that class of bug is gone with the
        # divisor).
        if not isinstance(factor, (int, float)) or factor < 0.0:
            factor = 0.0
        now = _game_time()
        for i in range(len(self._reload_timers)):
            prog = self._reload_timers[i]
            if prog == _SLOT_LOADED:
                continue
            game_dt = now - self._reload_advanced_at[i]
            if game_dt < 0.0:          # clock reset (e.g. mission swap) — don't credit
                game_dt = 0.0
            self._reload_timers[i] = prog + factor * game_dt
            self._reload_advanced_at[i] = now
        if native_combat._enabled:
            self._push_slots()
        for prog in self._reload_timers:
            if prog != _SLOT_LOADED and prog >= self._reload_delay:
                self.ReloadTorpedo()      # loads the MOST-PROGRESSED cooling slot
                return                    # one round per tick, as BC does

    def ReloadTorpedo(self) -> None:
        """Load one round into the longest-cooling slot. BC TorpedoTube::
        ReloadTorpedo (0x0057D8A0, weapon-firing-mechanics.md §2.2).

        BC says "find slot with greatest timer". Its timers count UP while
        cooling, so the greatest timer is the slot cooling LONGEST. We store the
        same accumulated-progress timer, so the equivalent is the LARGEST value —
        FIFO reload (weapon-firing-mechanics.md §2.2/§2.6).

        Ammo gate (BC §2.2 gate 2): reload iff AmmoCounts > NumReady — a round of
        this type exists in inventory that is not ALREADY chambered in one of the
        system's tubes. Checking only "inventory empty" let a second empty tube
        re-chamber a round already loaded elsewhere, so firing both over-issued.
        See _reload_denied_by_ammo. Unlimited/undeclared ammo never gates.

        Ammo is NOT decremented here. BC debits AmmoCounts at FIRE, not at reload:
        the decrement (0x0057B4D0) has exactly two callers, both TorpedoTube::Fire
        variants, and TorpedoSystem+0x118 is a loaded-in-tubes count, not a
        total-consumed counter (weapon-firing-mechanics.md §2.1/§2.2). Our fire-
        time debit (native fire control's launch) is therefore already aligned
        with BC — do NOT move it here; a debit at reload would double-count.
        """
        self._ensure_slots()
        if self._num_ready >= self._max_ready:
            return
        if self._reload_denied_by_ammo():
            return
        oldest_i, oldest_t = -1, None
        for i in range(len(self._reload_timers)):
            t = self._reload_timers[i]
            if t == _SLOT_LOADED:
                continue
            if oldest_t is None or t > oldest_t:   # largest progress = cooling longest
                oldest_i, oldest_t = i, t
        if oldest_i < 0:
            return
        self._reload_timers[oldest_i] = _SLOT_LOADED
        if native_combat._enabled:
            native_combat.push_field(self, "_reload_timers")
        self._num_ready += 1
        # K0 logs this reload's writes and queues TORPEDO_RELOAD itself
        # (k0_charging.h, THE EFFECT QUEUE): change both together.
        self._broadcast_reload()

    def _broadcast_reload(self) -> None:
        """Post ET_TORPEDO_RELOAD: Destination = the TUBE, NO Source.

        Both halves are MEASURED, from probe q12 against the original game
        (tools/probes/results/q12_torpedo_events.txt, e035):

            ET_TORPEDO_RELOAD | SRC None | DST TorpedoTube(name='Forward Torpedo 1' ready=1)

        Destination is load-bearing: ConditionTorpsReady.py:140 registers with a
        tube destination-filter, and :169 casts GetDestination() to a TorpedoTube.

        We previously set Source to the parent TorpedoSystem and labelled it "a
        CHOICE, not a finding". The probe says BC posts NO source. Corrected —
        do not re-add one.

        Inside the effect queue's scope it is queued (TORPEDO_RELOAD).
        """
        if effect_queue.deferring():
            effect_queue.post(effect_queue.TORPEDO_RELOAD, self)
            return
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_RELOAD)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_RELOAD broadcast", _e)

    def _broadcast_torpedo_fired(self, torp) -> None:
        """Post ET_TORPEDO_FIRED: Source = the PROJECTILE, Destination = the TUBE.

        Measured, from probe q12 against the original game
        (tools/probes/results/q12_torpedo_events.txt, e001):

            ET_TORPEDO_FIRED | SRC Torpedo(parent=13323 target=15013)
                             | DST TorpedoTube(name='Forward Torpedo 1' ready=0)

        ⚠️ THE DESTINATION IS DANGEROUS. Maelstrom/Episode7/Episode7.py:88-115
        listens for this event and DESTROYS pEvent.GetDestination() outright
        (MissionLib.SetConditionPercentage(pLauncher, 0)) on a 10% roll — the
        E7M1 phased-plasma story beat, where the unstable experimental torpedoes
        blow out the tube that fired them. Post this with the wrong destination
        and the game destroys the WRONG subsystem. It must be the TUBE.

        Posted UNCONDITIONALLY, for every torpedo: q12 captured `ammo=Photon` on
        every ET_TORPEDO_FIRED, so the engine does not filter by ammo type. The
        Phased-Plasma check lives in Episode7's HANDLER, not here.

        Only torpedo tubes post this. spawn_launch is shared with pulse
        cannons, hence the call site is here in TorpedoTube, not in that helper.

        Inside the effect queue's scope it is queued (TORPEDO_FIRED), ahead
        of the launch's WEAPON_FIRED and AMMO_CONSUMED (BC's order, EI R3).
        """
        if torp is None:
            return
        if effect_queue.deferring():
            effect_queue.post(effect_queue.TORPEDO_FIRED, self, torp)
            return
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_FIRED)
            evt.SetSource(torp)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_FIRED broadcast", _e)

    def UnloadTorpedo(self) -> None:
        """Remove one ready round; its slot goes back into cooldown.

        Mirrors BC's decompiled FUN_0057D9A0 (combat-and-damage.md:833-838),
        which stock BC calls on an ammo-type switch. TorpedoSystem.SetAmmoType
        calls it for every ready round of every tube when the selected slot
        actually CHANGES — stbc-oracle bible §4 T4 measured the switch
        unloading the Sovereign's tubes for one full ReloadDelay.

        Like BC it then posts ET_TORPEDO_FIRED: FUN_0057D9A0 ends in
        TorpedoTube_PostTorpedoFiredEvent(0) (0x0057DA20) — type 0x800066,
        source NULL, destination this tube. ConditionTorpsReady re-counts the
        tubes on that event; without it the gate stayed latched ready through
        the whole reload and FedAttack flew torpedo runs with every tube empty.
        The NULL source is what keeps Episode7.TorpedoFired (which destroys the
        destination tube on a roll) out: it bails when Torpedo_Cast fails."""
        if self._num_ready <= 0:
            return
        self._num_ready -= 1
        self._start_slot_cooldown(_game_time())
        self._broadcast_unload()

    def _broadcast_unload(self) -> None:
        """ET_TORPEDO_FIRED with NO source and the TUBE as destination — BC's
        unload notification (see UnloadTorpedo). Not _broadcast_torpedo_fired:
        that one carries the projectile and is skipped without one."""
        import App
        from engine import dev_mode
        try:
            evt = App.TGEvent_Create()
            evt.SetEventType(App.ET_TORPEDO_FIRED)
            evt.SetDestination(self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("ET_TORPEDO_FIRED (unload) broadcast", _e)

    def IsDumbFire(self) -> int:
        """Torpedo tubes are dumbfire-capable in BC (no guidance).
        Overrides Weapon.IsDumbFire() which returns 0."""
        return 1

    def SetSkewFire(self, flag) -> None:
        """Set skew-fire flag on this tube.  The flag is persistent and
        survives StopFiring (never cleared by firing lifecycle)."""
        self._skew_fire = bool(flag)

    def IsSkewFire(self) -> int:
        """Return 1 if skew-fire is enabled on this tube, else 0."""
        return 1 if self._skew_fire else 0
