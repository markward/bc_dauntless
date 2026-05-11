"""Bridge Phase 1 mission init/tick to the renderer host.

The constants below are placeholders pinned in Task 25 from the
pick_simplest_mission.py / pick_default_skybox.py scan results.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterable, Optional

from engine import renderer as r
from engine.scale import SHIP_SCALE, ASTRO_SCALE, PLANET_NIF_NATIVE_RADIUS

import math as _math


def _extract_ypr(R) -> tuple:
    """Yaw/pitch/roll in degrees from a BC row-vector TGMatrix3.

    BC convention: Row 0 = right, Row 1 = forward (Y), Row 2 = up (Z).
    Yaw:   atan2(forward.x, forward.y) - heading around world Z
    Pitch: asin(forward.z)             - elevation (+ = nose up)
    Roll:  atan2(-right.z, up.z)       - bank (+ = right wing down)
    """
    fwd = R.GetRow(1)
    up  = R.GetRow(2)
    rgt = R.GetRow(0)
    yaw_deg   = _math.degrees(_math.atan2(fwd.x, fwd.y))
    pitch_deg = _math.degrees(_math.asin(max(-1.0, min(1.0, fwd.z))))
    roll_deg  = _math.degrees(_math.atan2(-rgt.z, up.z))
    return yaw_deg, pitch_deg, roll_deg


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v1 ship-gate selections — Task 25 pins these from the pick_*.py scan results.
SHIP_GATE_MISSION = "Custom.Tutorial.Episode.M1Basic.M1Basic"
DEFAULT_TEXTURE_SEARCH = "data/Models/SharedTextures/FedShips/High"
DEFAULT_PLANET_TEXTURE_SEARCH = "data/Models/Environment"
DEFAULT_PLAYER_SET = "Biranu1"  # M1 Basic-specific

# Lighting defaults — used by both the per-tick fallback (when no active set
# has lights) and as the conceptual source of truth that the C++
# host_bindings.cc default-constructed Lighting struct mirrors.
DEFAULT_AMBIENT: tuple[float, float, float] = (0.1, 0.1, 0.1)
DEFAULT_DIRECTIONALS: list = [
    # Single top-down directional matching frame.cc's pre-Phase-1 default.
    # ((dx, dy, dz) toward light, (r, g, b))
    ((0.3, 1.0, 0.2), (1.0, 1.0, 1.0)),
]

# Camera-follow constants scaled to match SHIP_SCALE (original BC values: 600, 200).
CAM_BACK_DIST = 600.0 * SHIP_SCALE
CAM_UP_DIST   = 200.0 * SHIP_SCALE


class _PlayerControl:
    """Keyboard-driven ship-transform integrator.

    Throttle:
        1-9 → target speed = (level/9) × MaxSpeed
        0   → target = 0
        R   → target = -0.25 × MaxSpeed (BC's "reverse 1/4 impulse" idiom)

    Speed ramps from current toward target at MaxAccel rate (units/s²).
    Held W/S/A/D/Q/E turns at MaxAngularVelocity (no angular ramp in v1).

    When the ship has no ImpulseEngineSubsystem with non-zero MaxSpeed,
    falls back to legacy IMPULSE_UNIT × level so fake-ship tests and
    ships before SetupProperties has run still work.
    """

    # Legacy fallbacks — used when the live impulse subsystem isn't populated.
    TURN_RATE_RAD_PER_S = 1.5    # ~86°/s
    IMPULSE_UNIT        = 50.0   # BC units/s per level
    FALLBACK_MAX_ACCEL  = 1.0e9  # effectively instant — preserves legacy semantics
    REVERSE_LEVEL       = -2

    # Reverse magnitude as a fraction of MaxSpeed (BC convention: ¼ impulse).
    REVERSE_FRACTION = 0.25

    def __init__(self):
        self.impulse_level = 0  # signed: -2..9; 0 = stop
        self._current_speed = 0.0
        self._current_pitch_rate = 0.0
        self._current_yaw_rate   = 0.0
        self._current_roll_rate  = 0.0

    # ── Hardpoint accessors ──────────────────────────────────────────────────

    @staticmethod
    def _get_ies(player):
        getter = getattr(player, "GetImpulseEngineSubsystem", None)
        return getter() if getter else None

    def GetTargetSpeed(self, player) -> float:
        """Convert impulse_level into a target speed using the ship's
        ImpulseEngineProperty.MaxSpeed when present, or the legacy
        per-level placeholder otherwise."""
        ies = self._get_ies(player)
        max_speed = ies.GetMaxSpeed() if ies is not None else 0.0
        if max_speed > 0.0:
            if self.impulse_level >= 0:
                return (self.impulse_level / 9.0) * max_speed
            return -self.REVERSE_FRACTION * max_speed
        return self.impulse_level * self.IMPULSE_UNIT

    def GetCurrentSpeed(self) -> float:
        return self._current_speed

    def _max_accel(self, player) -> float:
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxSpeed() > 0.0:
            a = ies.GetMaxAccel()
            return a if a > 0.0 else self.FALLBACK_MAX_ACCEL
        return self.FALLBACK_MAX_ACCEL

    def _angular_rate(self, player) -> float:
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            return ies.GetMaxAngularVelocity()
        return self.TURN_RATE_RAD_PER_S

    def _angular_accel(self, player) -> float:
        """Per-axis angular acceleration (rad/s²).  When the IES has no
        MaxAngularAccel value, falls back to a very large rate so the legacy
        snap-to-rate semantics are preserved (tests using fake ships keep
        seeing instant rotation onset)."""
        ies = self._get_ies(player)
        if ies is not None and ies.GetMaxAngularVelocity() > 0.0:
            a = ies.GetMaxAngularAccel()
            return a if a > 0.0 else self.FALLBACK_MAX_ACCEL
        return self.FALLBACK_MAX_ACCEL

    def GetCurrentPitchRate(self) -> float: return self._current_pitch_rate
    def GetCurrentYawRate(self)   -> float: return self._current_yaw_rate
    def GetCurrentRollRate(self)  -> float: return self._current_roll_rate

    @staticmethod
    def _ramp_toward(current: float, target: float, step: float) -> float:
        delta = target - current
        if abs(delta) <= step:
            return target
        return current + (step if delta > 0 else -step)

    # ── Per-tick step ────────────────────────────────────────────────────────

    def apply(self, player, dt: float, h) -> None:
        """Read keys, update player transform.

        `h` is the _open_stbc_host bindings module (or any object with
        key_state, key_pressed, and `keys.KEY_*` attributes).
        """
        # 1. Throttle (one-shot edges).  R is checked before digits.
        if h.key_pressed(h.keys.KEY_R):
            self.impulse_level = self.REVERSE_LEVEL
        elif h.key_pressed(h.keys.KEY_0):
            self.impulse_level = 0
        else:
            digit_codes = [
                h.keys.KEY_1, h.keys.KEY_2, h.keys.KEY_3, h.keys.KEY_4,
                h.keys.KEY_5, h.keys.KEY_6, h.keys.KEY_7, h.keys.KEY_8,
                h.keys.KEY_9,
            ]
            for level, code in enumerate(digit_codes, start=1):
                if h.key_pressed(code):
                    self.impulse_level = level
                    break

        # 2. Linear speed ramp toward target at MaxAccel rate.
        self._current_speed = self._ramp_toward(
            self._current_speed,
            self.GetTargetSpeed(player),
            self._max_accel(player) * dt,
        )

        # 3. Angular rates: held keys set a per-axis target rate; current rate
        #    ramps toward target at MaxAngularAccel.
        # Sign convention (row-vector matrices, Y=forward, Z=up):
        #   +X rotation tilts forward (row 1) toward -Z = nose DOWN.
        #   +Z rotation tilts forward toward +X = yaw RIGHT.
        #   +Y rotation tilts up (row 2) toward -X = roll LEFT.
        ang_rate    = self._angular_rate(player)
        ang_step    = self._angular_accel(player) * dt
        pitch_target = 0.0
        yaw_target   = 0.0
        roll_target  = 0.0
        if h.key_state(h.keys.KEY_W): pitch_target += ang_rate
        if h.key_state(h.keys.KEY_S): pitch_target -= ang_rate
        if h.key_state(h.keys.KEY_A): yaw_target   += ang_rate
        if h.key_state(h.keys.KEY_D): yaw_target   -= ang_rate
        if h.key_state(h.keys.KEY_Q): roll_target  -= ang_rate
        if h.key_state(h.keys.KEY_E): roll_target  += ang_rate
        self._current_pitch_rate = self._ramp_toward(self._current_pitch_rate, pitch_target, ang_step)
        self._current_yaw_rate   = self._ramp_toward(self._current_yaw_rate,   yaw_target,   ang_step)
        self._current_roll_rate  = self._ramp_toward(self._current_roll_rate,  roll_target,  ang_step)
        pitch_rate = self._current_pitch_rate
        yaw_rate   = self._current_yaw_rate
        roll_rate  = self._current_roll_rate

        # 4. Rotation integration.  BC uses row-vector matrices where
        #    v_world = v_body * R, so the rows of R are the body axes in
        #    world space.  Composing a body-frame delta D means D acts on
        #    the body vector first: v_world = (v_body * D) * R = v_body *
        #    (D * R).  So body-frame rotation is PRE-multiply (D * R), not
        #    post-multiply.  Pitch → yaw → roll Euler order.
        from engine.appc.math import TGMatrix3, TGPoint3
        X_AXIS = TGPoint3(1.0, 0.0, 0.0)
        Y_AXIS = TGPoint3(0.0, 1.0, 0.0)
        Z_AXIS = TGPoint3(0.0, 0.0, 1.0)

        R = player.GetWorldRotation()
        if pitch_rate or yaw_rate or roll_rate:
            R_pitch = TGMatrix3(); R_pitch.MakeRotation(pitch_rate * dt, X_AXIS)
            R_yaw   = TGMatrix3(); R_yaw.MakeRotation(yaw_rate   * dt, Z_AXIS)
            R_roll  = TGMatrix3(); R_roll.MakeRotation(roll_rate  * dt, Y_AXIS)
            delta = R_pitch.MultMatrix(R_yaw).MultMatrix(R_roll)
            R = delta.MultMatrix(R)
            player.SetMatrixRotation(R)

        # 5. Position integration (forward = ship-local Y axis in world).
        if self._current_speed != 0.0:
            forward = R.GetRow(1)
            p = player.GetTranslate()
            player.SetTranslateXYZ(
                p.x + forward.x * self._current_speed * dt,
                p.y + forward.y * self._current_speed * dt,
                p.z + forward.z * self._current_speed * dt,
            )


class _CameraControl:
    """Arrow-key orbit + scroll-wheel zoom around the player ship.

    The orbit angles and distance are stored in the ship's body frame, so
    the camera "rotates with" the ship: when the ship banks/pitches/yaws,
    the relative camera position is preserved.

    Conventions:
      orbit_yaw_rad   — rotation around ship-Z. 0 = directly behind, +ve =
                        camera moves to ship-right, -ve = ship-left.
                        Wraps freely; not clamped.
      orbit_pitch_rad — elevation above the ship's XY plane. 0 = level with
                        the ship; +ve = camera above. Clamped to ±PITCH_LIMIT.
      distance        — eye-to-ship distance, multiplicative on scroll.

    Defaults reproduce the pre-orbit (-forward*600 + up*200) framing so
    existing setups look unchanged until the user touches arrows or scroll.
    """

    TURN_RATE_RAD_PER_S    = 1.5                                # ~86°/s
    ZOOM_FACTOR_PER_NOTCH  = 0.9                                # one scroll click ≈ 10%
    PITCH_LIMIT_RAD        = _math.radians(85)                  # avoid pole flip
    DEFAULT_YAW_RAD        = 0.0
    DEFAULT_PITCH_RAD      = _math.atan2(200.0, 600.0)          # ≈ 18.43°
    DEFAULT_DISTANCE       = _math.sqrt(600.0**2 + 200.0**2) * SHIP_SCALE
    DISTANCE_MIN           =  100.0 * SHIP_SCALE
    DISTANCE_MAX           = 5000.0 * SHIP_SCALE

    def __init__(self):
        self.orbit_yaw_rad   = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad = self.DEFAULT_PITCH_RAD
        self.distance        = self.DEFAULT_DISTANCE

    def _reset(self) -> None:
        self.orbit_yaw_rad   = self.DEFAULT_YAW_RAD
        self.orbit_pitch_rad = self.DEFAULT_PITCH_RAD
        self.distance        = self.DEFAULT_DISTANCE

    def apply(self, dt: float, h, scroll_y: float) -> None:
        """Read arrow keys + C reset + accumulated scroll, update orbit state.

        `h` is the bindings module (or fake) with key_state/key_pressed and a
        `keys` namespace containing KEY_LEFT/RIGHT/UP/DOWN/C.
        `scroll_y` is the total wheel delta accumulated since the last call.
        """
        if h.key_pressed(h.keys.KEY_C):
            self._reset()
            return

        if h.key_state(h.keys.KEY_RIGHT): self.orbit_yaw_rad   += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_LEFT):  self.orbit_yaw_rad   -= self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_UP):    self.orbit_pitch_rad += self.TURN_RATE_RAD_PER_S * dt
        if h.key_state(h.keys.KEY_DOWN):  self.orbit_pitch_rad -= self.TURN_RATE_RAD_PER_S * dt

        if self.orbit_pitch_rad >  self.PITCH_LIMIT_RAD: self.orbit_pitch_rad =  self.PITCH_LIMIT_RAD
        if self.orbit_pitch_rad < -self.PITCH_LIMIT_RAD: self.orbit_pitch_rad = -self.PITCH_LIMIT_RAD

        if scroll_y != 0.0:
            self.distance *= self.ZOOM_FACTOR_PER_NOTCH ** scroll_y
            if self.distance < self.DISTANCE_MIN: self.distance = self.DISTANCE_MIN
            if self.distance > self.DISTANCE_MAX: self.distance = self.DISTANCE_MAX

    def compute_camera(self, ship_loc, ship_rot) -> tuple:
        """Return (eye, target, up) as 3-tuples in world space.

        Offset is built in ship body frame (X=right, Y=forward, Z=up):
            offset_body = (sin(y)*cos(p), -cos(y)*cos(p), sin(p)) * distance
        At y=0, p=0 the camera sits directly behind on the body-Y axis.
        Mapping body→world uses BC's row-vector convention: world_axis_j =
        ship_rot.GetRow(j).
        """
        cy = _math.cos(self.orbit_yaw_rad)
        sy = _math.sin(self.orbit_yaw_rad)
        cp = _math.cos(self.orbit_pitch_rad)
        sp = _math.sin(self.orbit_pitch_rad)
        d  = self.distance

        ox =  sy * cp * d
        oy = -cy * cp * d
        oz =       sp * d

        rgt = ship_rot.GetRow(0)
        fwd = ship_rot.GetRow(1)
        up  = ship_rot.GetRow(2)

        eye = (
            ship_loc.x + ox * rgt.x + oy * fwd.x + oz * up.x,
            ship_loc.y + ox * rgt.y + oy * fwd.y + oz * up.y,
            ship_loc.z + ox * rgt.z + oy * fwd.z + oz * up.z,
        )
        target = (ship_loc.x, ship_loc.y, ship_loc.z)
        up_vec = (up.x, up.y, up.z)
        return eye, target, up_vec


def _setup_sdk() -> None:
    """Install SDK finder + AST transforms so SDK script imports work."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from tools import mission_harness
    mission_harness.setup_sdk()


def _init_mission(mission_module_name: str):
    """Initialize a mission via the same path gameloop_harness uses.

    Returns (mission, episode, game, mod) for the caller to use.
    """
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.events import TGEvent
    from engine.appc.placement import _waypoint_registry
    import App

    # Reset state per session (mirror tools/gameloop_harness.py).
    App.g_kTimerManager._time = 0.0
    App.g_kTimerManager._timers.clear()
    App.g_kRealtimeTimerManager._time = 0.0
    App.g_kRealtimeTimerManager._timers.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    App.g_kSetManager._sets.clear()
    _waypoint_registry.clear()
    App._next_event_type_id = 200

    mission = Mission()
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)

    mod = importlib.import_module(mission_module_name)
    if hasattr(mod, "PreLoadAssets"):
        mod.PreLoadAssets(mission)
    mod.Initialize(mission)

    start_evt = TGEvent()
    start_evt.SetEventType(App.ET_MISSION_START)
    start_evt.SetDestination(episode)
    App.g_kEventManager.AddEvent(start_evt)

    return mission, episode, game, mod


def _iter_set_objects(pSet) -> Iterable:
    """Walk every object in a set exactly once.

    Iterates `pSet._objects.values()` directly rather than using BC's
    GetFirstObject + GetNextObject API, because the latter is unreliable
    in the presence of stub objects: any object whose `GetObjID()` returns
    an `App._NamedStub` causes `SetClass.GetNextObject(stub).int(stub) → 0`
    to find no match and return None, terminating iteration prematurely.
    The `_objects` private attribute is already inspected elsewhere in this
    module (set-membership checks, verbose logging), so the implementation
    coupling is consistent.
    """
    for obj in getattr(pSet, "_objects", {}).values():
        yield obj


def _iter_ships(*, verbose: bool = False) -> Iterable:
    """Walk every ShipClass-like object in every active set."""
    import App
    for set_name, pSet in App.g_kSetManager._sets.items():
        if verbose:
            count = len(getattr(pSet, "_objects", {}))
            obj_keys = list(getattr(pSet, "_objects", {}).keys())
            print(f"[host_loop] set {set_name!r}: {count} object(s), keys={obj_keys}", flush=True)
        for obj in _iter_set_objects(pSet):
            # ShipClass exposes GetScript; non-ship objects (waypoints,
            # characters) typically don't have a non-empty script string.
            if hasattr(obj, "GetScript"):
                yield obj


def _iter_planets(*, verbose: bool = False) -> Iterable:
    """Walk every Planet (non-Sun) in every active set."""
    import App
    from engine.appc.planet import Planet, Sun
    for set_name, pSet in App.g_kSetManager._sets.items():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Planet) and not isinstance(obj, Sun):
                yield obj


def _iter_suns() -> Iterable:
    """Walk every Sun in every active set."""
    import App
    from engine.appc.planet import Sun
    for pSet in App.g_kSetManager._sets.values():
        for obj in _iter_set_objects(pSet):
            if isinstance(obj, Sun):
                yield obj


def _aggregate_suns() -> list:
    """Collect sun render descriptors with ASTRO_SCALE applied to position and radii."""
    from engine.appc.planet import aggregate_suns_for_renderer
    import App
    raw = aggregate_suns_for_renderer(
        PROJECT_ROOT, list(App.g_kSetManager._sets.values()))
    return [
        {
            "position": (
                d["position"][0] * ASTRO_SCALE,
                d["position"][1] * ASTRO_SCALE,
                d["position"][2] * ASTRO_SCALE,
            ),
            "radius":            d["radius"]        * ASTRO_SCALE,
            "base_texture_path": d["base_texture_path"],
            "corona_radius":     d["corona_radius"] * ASTRO_SCALE,
        }
        for d in raw
    ]


def _planet_nif_path(planet, *, verbose: bool = False) -> Optional[str]:
    """Return absolute path to the planet's NIF, or None if unavailable."""
    rel = planet.GetModelPath()
    if not rel:
        if verbose:
            print(f"[host_loop]   skip planet: GetModelPath() returned empty", flush=True)
        return None
    abs_path = PROJECT_ROOT / "game" / rel
    if not abs_path.is_file():
        if verbose:
            print(f"[host_loop]   skip planet: NIF not found at {abs_path}", flush=True)
        return None
    return str(abs_path)


def _ship_nif_path(ship, *, verbose: bool = False) -> Optional[str]:
    """Return absolute path to the ship's high-LOD NIF, or None if not found.

    When verbose is True, prints the specific reason for any None return
    (script lookup, import, stats access, file-not-found) so the host's
    diagnostic mode can surface why ships aren't getting render instances.
    """
    try:
        script_name = ship.GetScript()
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: ship.GetScript() raised: {e!r}", flush=True)
        return None
    if not script_name:
        if verbose:
            print(f"[host_loop]   skip: ship.GetScript() returned empty: {script_name!r}", flush=True)
        return None
    try:
        mod = importlib.import_module(script_name)
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: import_module({script_name!r}) raised: {type(e).__name__}: {e}", flush=True)
        return None
    try:
        stats = mod.GetShipStats()
    except Exception as e:
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() raised: {type(e).__name__}: {e}", flush=True)
        return None
    if not isinstance(stats, dict):
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() returned non-dict: {type(stats).__name__}", flush=True)
        return None
    rel = stats.get("FilenameHigh")
    if not rel:
        if verbose:
            print(f"[host_loop]   skip: {script_name}.GetShipStats() missing 'FilenameHigh' (keys: {list(stats.keys())})", flush=True)
        return None
    abs_path = PROJECT_ROOT / "game" / rel
    if not abs_path.is_file():
        if verbose:
            print(f"[host_loop]   skip: NIF file not found at {abs_path}", flush=True)
        return None
    return str(abs_path)


def _resolve_active_set(player):
    """Return the SetClass whose lights & backdrops apply to the rendered
    scene. Order:
      1. g_kSetManager.GetRenderedSet() — set explicitly via
         MissionLib.MakeRenderedSet during scene transitions.
      2. The set containing the player ship — Phase 1 fallback.
      3. None — caller falls through to per-system defaults
         (lighting only; backdrops simply absent).

    Considers both _lights and _backdrops when deciding whether a set
    is 'live' so backdrop-only sets (rare but legal) are picked up.
    """
    import App
    rendered = App.g_kSetManager.GetRenderedSet()
    if rendered is not None and (
        getattr(rendered, "_lights", None) or
        getattr(rendered, "_backdrops", None)
    ):
        return rendered
    if player is not None:
        for s in App.g_kSetManager._sets.values():
            if any(o is player for o in getattr(s, "_objects", {}).values()):
                if (getattr(s, "_lights", None) or
                    getattr(s, "_backdrops", None)):
                    return s
    return None


# Back-compat alias — existing lighting tests reference this name.
_resolve_active_lighting_set = _resolve_active_set


def _aggregate_lights(pSet):
    """Thin wrapper over engine.appc.lights.aggregate_for_renderer that
    plugs in this module's DEFAULT_AMBIENT / DEFAULT_DIRECTIONALS. Kept
    as a private symbol so existing tests and call sites don't have to
    juggle the defaults at every call site."""
    from engine.appc.lights import aggregate_for_renderer
    return aggregate_for_renderer(pSet, DEFAULT_AMBIENT, DEFAULT_DIRECTIONALS)


def _aggregate_backdrops(pSet):
    """Thin wrapper over engine.appc.backdrops.aggregate_for_renderer
    that supplies PROJECT_ROOT, mirroring _aggregate_lights's wrapping
    of aggregate_for_renderer in lights.py."""
    from engine.appc.backdrops import aggregate_for_renderer
    return aggregate_for_renderer(pSet, PROJECT_ROOT)


def _ship_world_matrix(ship) -> list:
    """Row-major TRS mat4 for a ship: mesh scaled by SHIP_SCALE, position unchanged.

    BC's TGMatrix3 is row-vector (rows = body axes in world). The OpenGL shader
    consumes u_model column-vector (columns = body axes), so the rotation is
    transposed on the way out. Camera and physics-motion code keep reading
    rows and stay correct under BC convention.
    """
    loc = ship.GetWorldLocation()
    rot = ship.GetWorldRotation()
    s = SHIP_SCALE
    return [
        rot._m[0][0]*s, rot._m[1][0]*s, rot._m[2][0]*s, loc.x,
        rot._m[0][1]*s, rot._m[1][1]*s, rot._m[2][1]*s, loc.y,
        rot._m[0][2]*s, rot._m[1][2]*s, rot._m[2][2]*s, loc.z,
        0.0,            0.0,            0.0,            1.0,
    ]


def _astro_world_matrix(obj) -> list:
    """Row-major TRS mat4 for a planet/moon: position * ASTRO_SCALE, mesh scale
    derived from GetRadius() so the visual radius equals python_radius * ASTRO_SCALE.

    Rotation is transposed for the same row/column convention reason as
    _ship_world_matrix.
    """
    loc = obj.GetWorldLocation()
    rot = obj.GetWorldRotation()
    s = obj.GetRadius() * ASTRO_SCALE / PLANET_NIF_NATIVE_RADIUS
    return [
        rot._m[0][0]*s, rot._m[1][0]*s, rot._m[2][0]*s, loc.x * ASTRO_SCALE,
        rot._m[0][1]*s, rot._m[1][1]*s, rot._m[2][1]*s, loc.y * ASTRO_SCALE,
        rot._m[0][2]*s, rot._m[1][2]*s, rot._m[2][2]*s, loc.z * ASTRO_SCALE,
        0.0,            0.0,            0.0,            1.0,
    ]


def run(mission_name: str = SHIP_GATE_MISSION,
        max_ticks: Optional[int] = None) -> int:
    """Boot the renderer, init the named mission, run until the window closes
    or max_ticks is reached. Returns 0 on clean exit.

    Debug knobs (env vars):
      OPEN_STBC_HOST_HEADLESS=1     — hide the window (used by tests).
      OPEN_STBC_HOST_VERBOSE=1      — print loaded ships, player position,
                                      camera state on the first tick.
      OPEN_STBC_HOST_FIXED_CAMERA=1 — ignore third-person follow; use a
                                      fixed camera at (0, 0, 150) looking
                                      at the world origin.
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"

    _setup_sdk()
    _init_mission(mission_name)

    import App
    from engine.core.loop import GameLoop

    r.init(1280, 720, "open_stbc",
           str(PROJECT_ROOT / "native" / "assets" / "ui"))
    try:
        # Demo UI panel — proves the components render. Remove once a real
        # consumer (mission picker, targets panel) replaces it.
        from engine import ui
        ui.init()
        demo_panel = ui.UiPanel(id="demo", anchor="top-left",
                                width_vw=18.0, height_vh=55.0,
                                title="Targets", collapsible=True)
        bop = demo_panel.collapsible("Bird of Prey-1", affiliation="enemy",
                                     expanded=True)
        bop.button("Shield Generator")
        bop.button("Warp Core", selected=True)
        bop.collapsible("Disruptor Cannons", menu_level=3, expanded=False)
        bop.button("Torpedoes")
        bop.button("Impulse Engines")
        bop.collapsible("Warp Engines", menu_level=3, expanded=False)
        bop.button("Cloaking Device")
        bop.button("Sensor Array")
        demo_panel.collapsible("USS Yamato", affiliation="friendly",
                               expanded=False)
        demo_panel.collapsible("Tellarite Caravan", affiliation="neutral",
                               expanded=False)
        demo_panel.collapsible("Subspace Echo 47", affiliation="unknown",
                               expanded=False)

        # Per-NIF cache so the same mesh isn't reloaded once per ship.
        nif_to_handle: dict[str, int] = {}
        ship_instances: dict[object, object] = {}    # ship   -> InstanceId
        planet_instances: dict[object, object] = {}  # planet -> InstanceId
        ships_seen = 0
        for ship in _iter_ships(verbose=verbose):
            ships_seen += 1
            if verbose:
                cls = type(ship).__name__
                try:
                    sn = ship.GetScript()
                except Exception:
                    sn = "<no script>"
                print(f"[host_loop] consider ship: class={cls} script={sn!r}", flush=True)
            nif_path = _ship_nif_path(ship, verbose=verbose)
            if nif_path is None:
                continue
            handle = nif_to_handle.get(nif_path)
            if handle is None:
                tex_search = str(PROJECT_ROOT / "game" / DEFAULT_TEXTURE_SEARCH)
                try:
                    handle = r.load_model(nif_path, tex_search)
                except Exception as e:
                    if verbose:
                        print(f"[host_loop]   skip: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                nif_to_handle[nif_path] = handle
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _ship_world_matrix(ship))
            ship_instances[ship] = iid
        if verbose:
            print(f"[host_loop] ships seen by iterator: {ships_seen}; "
                  f"instances created: {len(ship_instances)}", flush=True)

        planets_seen = 0
        planet_tex_search = str(PROJECT_ROOT / "game" / DEFAULT_PLANET_TEXTURE_SEARCH)
        for planet in _iter_planets(verbose=verbose):
            planets_seen += 1
            nif_path = _planet_nif_path(planet, verbose=verbose)
            if nif_path is None:
                continue
            handle = nif_to_handle.get(nif_path)
            if handle is None:
                try:
                    handle = r.load_model(nif_path, planet_tex_search)
                except Exception as e:
                    if verbose:
                        print(f"[host_loop]   skip planet: load_model({nif_path}) raised: "
                              f"{type(e).__name__}: {e}", flush=True)
                    continue
                nif_to_handle[nif_path] = handle
            iid = r.create_instance(handle)
            r.set_world_transform(iid, _astro_world_matrix(planet))
            planet_instances[planet] = iid
        if verbose:
            print(f"[host_loop] planets seen: {planets_seen}; "
                  f"planet instances created: {len(planet_instances)}", flush=True)

        # Player ship for camera follow.
        player_set = App.g_kSetManager.GetSet(DEFAULT_PLAYER_SET)
        player = player_set.GetObject("player") if player_set is not None else None
        if player is None and ship_instances:
            # Fallback: follow the first ship we found.
            player = next(iter(ship_instances.keys()))

        if verbose:
            print(f"[host_loop] mission={mission_name}", flush=True)
            total = len(ship_instances) + len(planet_instances)
            print(f"[host_loop] {total} render instance(s) created "
                  f"({len(ship_instances)} ships, {len(planet_instances)} planets)", flush=True)
            for ship, _iid in list(ship_instances.items())[:5]:
                p = ship.GetWorldLocation()
                print(f"[host_loop]   ship script={ship.GetScript()!r} "
                      f"world=({p.x:.2f}, {p.y:.2f}, {p.z:.2f})", flush=True)
            if player is not None:
                pp = player.GetWorldLocation()
                cls = type(player).__name__
                try:
                    sn = player.GetScript()
                except Exception as e:
                    sn = f"<GetScript raised: {e!r}>"
                # Where does the player live? Check every set for membership.
                in_sets = []
                for sname, pset in App.g_kSetManager._sets.items():
                    if any(o is player for o in getattr(pset, "_objects", {}).values()):
                        in_sets.append(sname)
                print(f"[host_loop] player class={cls} script={sn!r} "
                      f"world=({pp.x:.2f}, {pp.y:.2f}, {pp.z:.2f}) "
                      f"in_sets={in_sets}", flush=True)
            else:
                print("[host_loop] no player ship found", flush=True)

        # Per-tick player input → ship-transform integrator.
        player_control = _PlayerControl()
        cam_control    = _CameraControl()
        try:
            import _open_stbc_host as _h
        except ImportError:
            _h = None  # bindings module not built; skip input handling.
        # Bindings older than the orbit-camera change won't expose
        # consume_scroll_y; fall back to a zero-delta lambda so host_loop
        # still runs against an old _open_stbc_host.so without rebuilding.
        _consume_scroll = getattr(_h, "consume_scroll_y", None) if _h else None
        TICK_DT = 1.0 / 60.0

        loop = GameLoop()
        ticks = 0
        while not r.should_close():
            loop.tick()

            # F8 toggles the RmlUi debugger overlay.
            if _h is not None and _h.key_pressed(_h.keys.KEY_F8):
                _h.toggle_ui_debugger()

            # Apply keyboard input to the player ship's transform and to the
            # orbit camera. Scroll delta is consumed once per tick; old
            # bindings without the binding return 0.0 via the fallback.
            scroll_y = _consume_scroll() if _consume_scroll is not None else 0.0
            if player is not None and _h is not None:
                player_control.apply(player, TICK_DT, _h)
                cam_control.apply(TICK_DT, _h, scroll_y)

            # Sync transforms for known instances.
            for ship, iid in ship_instances.items():
                r.set_world_transform(iid, _ship_world_matrix(ship))
            for planet, iid in planet_instances.items():
                r.set_world_transform(iid, _astro_world_matrix(planet))

            # Camera: orbit + zoom around the player ship (or origin fallback).
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0 * SHIP_SCALE)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            elif player is not None:
                eye, target, up_vec = cam_control.compute_camera(
                    player.GetWorldLocation(), player.GetWorldRotation())
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
                up_vec = (0.0, 1.0, 0.0)
            r.set_camera(eye=eye, target=target, up=up_vec,
                         fov_y_rad=1.0472, near=1.0, far=2_000_000.0)

            active_set = _resolve_active_set(player)

            if player is not None:
                _R = player.GetWorldRotation()
                _p = player.GetWorldLocation()
                _yaw, _pitch, _roll = _extract_ypr(_R)
                _set_name = next(
                    (n for n, s in App.g_kSetManager._sets.items()
                     if s is active_set),
                    ""
                ) if active_set is not None else ""
                try:
                    _raw_script = player.GetScript() or ""
                except Exception:
                    _raw_script = ""
                _ship_display = _raw_script.split(".")[-1] if _raw_script else "---"
                r.set_hud_state({
                    "pos":    (_p.x, _p.y, _p.z),
                    "yaw":    _yaw,
                    "pitch":  _pitch,
                    "roll":   _roll,
                    "system": _set_name or "---",
                    "ship":   _ship_display,
                })

            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)

            backdrops = _aggregate_backdrops(active_set)
            r.set_backdrops(backdrops)

            suns = _aggregate_suns()
            r.set_suns(suns)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)
                print(f"[host_loop] tick 0 lighting ambient={ambient} "
                      f"directionals={directionals}", flush=True)
                print(f"[host_loop] tick 0 backdrops: "
                      f"{len(backdrops)} layer(s)", flush=True)
                print(f"[host_loop] tick 0 suns: {len(suns)} sun(s)", flush=True)

            r.frame()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break

        for iid in ship_instances.values():
            r.destroy_instance(iid)
        for iid in planet_instances.values():
            r.destroy_instance(iid)
    finally:
        r.shutdown()

    return 0
