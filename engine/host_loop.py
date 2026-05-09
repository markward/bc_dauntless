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

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v1 ship-gate selections — Task 25 pins these from the pick_*.py scan results.
SHIP_GATE_MISSION = "Custom.Tutorial.Episode.M1Basic.M1Basic"
DEFAULT_SKYBOX_NIF: Optional[str] = None  # No skybox NIF in BC assets; spec defers
DEFAULT_TEXTURE_SEARCH = "data/Models/SharedTextures/FedShips/High"
DEFAULT_PLAYER_SET = "Biranu1"  # M1 Basic-specific

# Camera-follow constants used by run() to position the third-person camera.
CAM_BACK_DIST = 600.0
CAM_UP_DIST   = 200.0


class _PlayerControl:
    """Keyboard-driven ship-transform integrator.

    Reads keys via a duck-typed `h` (the _open_stbc_host bindings module
    or a test fake) and updates the player's transform each tick. v1
    writes _position / _rotation directly because Phase 1's
    engine/physics/simulation.py is empty; when physics lands, this
    becomes target-velocity / target-heading instead.
    """

    TURN_RATE_RAD_PER_S = 1.5   # ~86°/s — half-turn in ~2.1s
    IMPULSE_UNIT        = 50.0  # BC units/s per impulse level
    REVERSE_LEVEL       = -2    # signed level set by R key

    def __init__(self):
        self.impulse_level = 0  # signed: -2..9; 0 = stop

    def apply(self, player, dt: float, h) -> None:
        """Read keys, update player transform.

        `h` is the _open_stbc_host bindings module (or any object with
        key_state, key_pressed, and `keys.KEY_*` attributes).
        """
        # 1. Throttle (one-shot edges). R is checked before digits so a
        #    simultaneous R + digit press picks R; in practice no human
        #    would do that on the same frame.
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

        # Tasks 5 and 6 add rotation and position integration here.


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


def _world_matrix_row_major(ship) -> list:
    """Convert ship's world-space pose to a 16-float row-major mat4."""
    loc = ship.GetWorldLocation()
    rot = ship.GetWorldRotation()
    return [
        rot._m[0][0], rot._m[0][1], rot._m[0][2], loc.x,
        rot._m[1][0], rot._m[1][1], rot._m[1][2], loc.y,
        rot._m[2][0], rot._m[2][1], rot._m[2][2], loc.z,
        0.0,          0.0,          0.0,          1.0,
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
                                      fixed camera at (0, 0, 1500) looking
                                      at the world origin (matches the
                                      headless ship-gate test that's known
                                      to frame the Galaxy correctly).
    """
    import os as _os
    verbose = _os.environ.get("OPEN_STBC_HOST_VERBOSE") == "1"
    fixed_camera = _os.environ.get("OPEN_STBC_HOST_FIXED_CAMERA") == "1"

    _setup_sdk()
    _init_mission(mission_name)

    import App
    from engine.core.loop import GameLoop

    r.init(1280, 720, "open_stbc")
    try:
        if DEFAULT_SKYBOX_NIF:
            sky = r.load_model(DEFAULT_SKYBOX_NIF, DEFAULT_TEXTURE_SEARCH)
            r.set_skybox(sky)

        # Per-NIF cache so the same mesh isn't reloaded once per ship.
        nif_to_handle: dict[str, int] = {}
        instances: dict[object, object] = {}  # ship -> InstanceId
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
            r.set_world_transform(iid, _world_matrix_row_major(ship))
            instances[ship] = iid
        if verbose:
            print(f"[host_loop] ships seen by iterator: {ships_seen}; "
                  f"instances created: {len(instances)}", flush=True)

        # Player ship for camera follow.
        player_set = App.g_kSetManager.GetSet(DEFAULT_PLAYER_SET)
        player = player_set.GetObject("player") if player_set is not None else None
        if player is None and instances:
            # Fallback: follow the first ship we found.
            player = next(iter(instances.keys()))

        if verbose:
            print(f"[host_loop] mission={mission_name}", flush=True)
            print(f"[host_loop] {len(instances)} render instance(s) created", flush=True)
            for ship, _iid in list(instances.items())[:5]:
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

        loop = GameLoop()
        ticks = 0
        while not r.should_close():
            loop.tick()

            # Sync transforms for known instances.
            for ship, iid in instances.items():
                r.set_world_transform(iid, _world_matrix_row_major(ship))

            # Camera: third-person offset behind the player ship (or origin).
            if fixed_camera:
                eye = (0.0, 0.0, 1500.0)
                target = (0.0, 0.0, 0.0)
            elif player is not None:
                p = player.GetWorldLocation()
                eye = (p.x, p.y + 30.0, p.z + 200.0)
                target = (p.x, p.y, p.z)
            else:
                eye = (0.0, 30.0, 200.0)
                target = (0.0, 0.0, 0.0)
            r.set_camera(eye=eye, target=target, up=(0.0, 1.0, 0.0),
                         fov_y_rad=1.0472, near=1.0, far=100000.0)

            if verbose and ticks == 0:
                print(f"[host_loop] tick 0 camera eye={eye} target={target}", flush=True)

            r.frame()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break

        for iid in instances.values():
            r.destroy_instance(iid)
    finally:
        r.shutdown()

    return 0
