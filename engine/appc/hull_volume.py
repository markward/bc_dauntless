"""Push BC's authored damage-volume resolution to the hull-volume baker.

`ShipProperty.SetDamageResolution` is authored per ship in every hardpoint file
-- Shuttle 6, Akira 8, Galaxy 10, Warbird 12, stations 15 -- and copied onto the
ship by `ShipClass` property application. Until now nothing read it.

It is NOT a cell size: it is a per-ship detail RATIO (Shuttle 6, Akira 8,
Galaxy 10, Warbird 12, stations 15). The native baker (`HullVolumeCache::get`)
derives the actual bake cell size, in model units, as `authored_res / quality`,
where quality is a global fidelity multiplier -- see
`native/src/voxel/include/voxel/hull_volume_cache.h`. It is also finer than
what BC itself shipped (Galaxy 10 vs a baked 15, Akira 8
vs 15, Warbird 12 vs 25) -- and the Warbird, the worst mismatch in the fleet, is
exactly the ship whose breaches were seen cutting into nothing.

See docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md
"""
import importlib
import re
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from engine import renderer as _renderer

__all__ = ["push_resolution", "prewarm_field",
           "discover_bake_targets", "prebake_all"]


def push_resolution(ship, iid) -> bool:
    """Send `ship`'s authored resolution for instance `iid`.

    Returns True only when a positive resolution was actually pushed. A ship
    that never had one keeps the native default rather than being handed 0.0,
    which the baker would divide by.

    A missing/non-numeric GetDamageResolution is a data problem on the ship,
    not an engine fault, and is swallowed (returns False). A failure from the
    renderer call itself -- a stale .so missing the binding, a broken pybind
    arg type -- is NOT swallowed here: it propagates so the caller can log it.
    Both host_loop call sites wrap this call in their own
    try/except + dev_mode.log_swallowed, which is the intended visibility
    mechanism for that class of failure; catching it here too would silently
    disable that logging forever, indistinguishable from "no ship authored a
    resolution".
    """
    getter = getattr(ship, "GetDamageResolution", None)
    if getter is None:
        return False
    try:
        resolution = float(getter())
    except (TypeError, ValueError):
        return False
    if not resolution > 0.0:
        return False
    _renderer.hull_volume_set_resolution(iid, resolution)
    return True


def prewarm_field(iid) -> None:
    """Force this instance's hull damage field to bake now, at spawn time.

    Design spec §4 puts the bake "on first use of a hull, during model
    load" -- without a pre-warm call, nothing runs `HullVolumeCache::get`
    until the FIRST `hull_carve_add` deposit against that hull, which
    happens mid-combat. That bake is a full NIF re-parse, voxelization, a
    distance transform, and up to a ~2.4 MB `.dhv` write: spec-measured at
    57ms (Galor) to 192ms (Warbird) -- 4-12 dropped frames the first time
    the player hits each new hull class. Calling this right after
    `push_resolution`, at spawn, moves that cost to mission load instead,
    matching the spec.

    No-op (not an error) when no authored resolution has been pushed for
    this hull -- there is nothing to bake at the native default.

    Same error contract as `push_resolution`: a real failure from the
    renderer call itself (a stale .so missing the binding, a broken pybind
    arg type) is NOT swallowed here -- it propagates so the caller can log
    it. Both host_loop call sites wrap this call in their own
    try/except + dev_mode.log_swallowed, exactly as they already do for
    push_resolution, so a prewarm failure can never block a spawn.
    """
    _renderer.hull_volume_prewarm(iid)


# ── Boot-time pre-bake ─────────────────────────────────────────────────────
#
# prewarm_field moved the bake from "first combat hit" to "spawn". That was
# sized from ships (57-192 ms) and was fine until the first E1M1 warp to
# Starbase 12 paid a multi-second FedStarbase bake at arrival -- after the
# lattice budget (voxel::kMaxFieldCells) stopped it being a 28.7-billion-cell
# crash. So: at game load, find every hull the runtime could spawn and bake
# whatever .dhv is missing or stale on a daemon thread, smallest hull first.
# By the time a mission spawns a hull, HullVolumeCache::get finds the file.
# Correctness never depends on this: a spawn that outruns the worker just
# pays today's synchronous bake for that one hull.
#
# The cache is keyed on (ABSOLUTE hull path, authored resolution, quality),
# so discovery must resolve exactly the pair the spawn path resolves --
# host_loop._ship_nif_path's `paths.game_asset(GetShipStats()["FilenameHigh"])`
# and the hardpoint's SetDamageResolution -- or it bakes entries nothing will
# ever hit. FilenameHigh only: the field is built for the high LOD, and the
# medium/low LODs (if we ever load them) are drawn without damage.

_DAMAGE_RESOLUTION = re.compile(r"\.SetDamageResolution\(\s*([0-9.]+)\s*\)")

# Injectable for tests (which serve fake ship modules without touching
# sys.modules); the runtime default is exactly what _ship_nif_path uses.
_import_ship_module: Callable = importlib.import_module


def _parse_damage_resolution(text: str) -> Optional[float]:
    """The authored SetDamageResolution in a hardpoint file's text, or None
    when absent or non-positive (the baker divides by it, and 0 is the
    'never pushed' value at spawn too). Read as text, not executed: running
    50 hardpoint files at boot would register every ship's property set
    before any mission asked for it."""
    m = _DAMAGE_RESOLUTION.search(text)
    if m is None:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return value if value > 0.0 else None


def _hardpoint_path(name: str) -> Optional[Path]:
    """ships/Hardpoints/<name>.py through the same overlay the SDK finder
    honours: a mod's copy wins, else the stock SDK. None when neither has
    it (GenericTemplate declares "blahblah")."""
    from engine import mods, paths
    rel = f"ships/Hardpoints/{name}.py"
    override = mods.sdk_override(rel)
    if override is not None and override.is_file():
        return override
    stock = paths.sdk_scripts() / "ships" / "Hardpoints" / f"{name}.py"
    return stock if stock.is_file() else None


_SHIP_SCRIPT_KEY = re.compile(r"^ships/([^/]+)\.py$")


def _ship_script_names() -> List[str]:
    """Every ships/<Name>.py the runtime could import: stock, plus any a mod
    overlays or adds. Names keep the file's own spelling -- it is what
    ship.GetScript() returns and what the import system resolves."""
    from engine import mods, paths
    names = {}
    stock = paths.sdk_scripts() / "ships"
    if stock.is_dir():
        for p in stock.glob("*.py"):
            if p.stem != "__init__":
                names[p.stem.lower()] = p.stem
    for key, mf in mods.current().files.items():
        if mf.target != "sdk":  # paths-guard: kind label
            continue
        if _SHIP_SCRIPT_KEY.match(key) is None:
            continue
        stem = Path(mf.abs_path).stem
        if stem != "__init__":
            names[stem.lower()] = stem
    return sorted(names.values())


def _bake_target_for(name: str) -> Optional[Tuple[Path, float]]:
    """(absolute high-LOD NIF, authored resolution) for one ship script, or
    None when any link in the chain is missing. Every None is a skip: a
    template, a mod ship without its base, a hull file not installed."""
    from engine import paths
    try:
        stats = _import_ship_module(f"ships.{name}").GetShipStats()
    except Exception:  # noqa: BLE001 - one bad script must not stop discovery
        return None
    if not isinstance(stats, dict):
        return None
    rel = stats.get("FilenameHigh")
    hp = stats.get("HardpointFile")
    if not rel or not hp:
        return None
    hp_path = _hardpoint_path(str(hp))
    if hp_path is None:
        return None
    try:
        res = _parse_damage_resolution(hp_path.read_text(errors="replace"))
    except OSError:
        return None
    if res is None:
        return None
    nif = Path(paths.game_asset(rel))
    if not nif.is_file():
        return None
    return nif, res


def discover_bake_targets() -> List[Tuple[Path, float]]:
    """Every (absolute hull NIF, authored resolution) pair the runtime could
    ask the cache for, smallest NIF first -- a cheap proxy for bake cost, so
    the most hulls are warm soonest and the 16 MB stations go last. Runs on
    the main thread (it imports ship scripts through the SDK finder, whose
    override hooks are not thread-safe); ~50 tiny modules, well under the
    cost of one bake."""
    targets = []
    for name in _ship_script_names():
        t = _bake_target_for(name)
        if t is not None:
            targets.append(t)
    # Dedupe: two scripts can name the same hull at the same resolution.
    seen = set()
    unique = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    def size_of(t):
        try:
            return t[0].stat().st_size
        except OSError:
            return 0

    unique.sort(key=size_of)
    return unique


def prebake_all() -> Optional[threading.Thread]:
    """Start the boot-time pre-bake. Returns the daemon thread (so a caller
    can join it -- tests do; boot never does), or None when there is
    nothing to bake.

    Discovery happens HERE, on the caller's thread; only the bakes run on
    the worker. Each bake is one call to the GIL-releasing
    renderer.hull_volume_bake_to_disk, which touches only the filesystem --
    the native cache's memo is never shared with this thread. A failing hull
    is logged (developer mode) and skipped; the rest still bake.
    """
    targets = discover_bake_targets()
    if not targets:
        return None

    def work():
        from engine import dev_mode
        t0 = time.monotonic()
        baked = 0
        for nif, res in targets:
            try:
                if _renderer.hull_volume_bake_to_disk(str(nif), res):
                    baked += 1
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                dev_mode.log_swallowed(f"prebake hull volume {nif.name}", exc)
        if dev_mode.is_enabled():
            print(f"[hull_volume] prebake: {baked}/{len(targets)} hulls "
                  f"valid on disk in {time.monotonic() - t0:.1f}s",
                  flush=True)

    thread = threading.Thread(target=work, name="hull-volume-prebake",
                              daemon=True)
    thread.start()
    return thread
