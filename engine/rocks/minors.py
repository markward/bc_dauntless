"""Which minor-rock clouds exist for the viewed set (minor-rocks spec §1, §4).

Python owns the cloud LIST; native (renderer.minors_*) owns the instances.
Every frame `reconcile` derives the desired clouds from the viewed set --

  halo:<rock>          one per realised RockClass, anchored to its instance
  tile:<set>:<field>   one per BC AsteroidField, a uniform sphere at a point
  free:<set>:<rock>    a dead rock's halo + breakup debris, drifting freely
                       (queued by rocks/death.py through register_free_cloud)

-- and sends native only the difference (adds / removes by key). A spec whose
numbers change (a dial rebuild, a view change moving a point) is removed and
re-added. Free clouds live here per set and are re-sent when their set is
viewed again; over the live-minor budget the oldest free cloud fades out and
is dropped. Halos and tile fields are never evicted.

Every native call is wrapped: rendering can never break the frame. Nothing
here reads a path or the catalogue at import.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Optional

from engine.rocks import minor_dials as md

_ZERO = (0.0, 0.0, 0.0)
_FAMILY_NAME = {i: n for n, i in md.FAMILY_INDEX.items()}


@dataclass(frozen=True)
class CloudSpec:
    """The native desc (renderer.minors_add_cloud) minus `id`, plus `key`.
    `fade_in` is decided when the cloud is ADDED (registry state, not the
    cloud's numbers), so desired specs always carry False and compare equal
    frame to frame."""
    key: str
    anchor: str                  # "instance" | "point" | "free"
    instance: object             # renderer InstanceId for "instance", else None
    point: tuple                 # VIEW space ("point" / "free" p0)
    velocity: tuple              # GU/s ("free")
    t0: float                    # game time ("free")
    shell_inner: float
    shell_outer: float
    falloff: float
    count: int
    r_min: float
    r_max: float
    size_exponent: float
    family: int                  # minor_dials.FAMILY_INDEX
    seed: int
    orbit_rate: float
    fade_in: bool = False
    debris: tuple = ()           # tuple of dict(offset, v0, radius, seed)


@dataclass(frozen=True)
class FreeCloudSpec:
    rock_name: str
    pSet: object                 # the set the rock died in
    p0: tuple                    # pSet coordinates
    velocity: tuple              # GU/s
    t0: float                    # game time
    family: str
    debris: tuple                # tuple of dict(offset, v0, radius, seed)
    halo_radius_gu: float        # the parent's effective radius (halo rebuild)


@dataclass
class _FreeEntry:
    spec: FreeCloudSpec
    seq: int                     # registration order: lower = older
    key: str = field(default="")


# ── Module state (all cleared by reset) ───────────────────────────────────────
_ids: dict = {}                  # key -> native cloud id
_specs: dict = {}                # key -> CloudSpec native holds
_next_id = 1
_free: dict = {}                 # set name -> [_FreeEntry]
_free_seq = 0
_pending_free: list = []
_fragments_loaded: set = set()
_UNSEEN = object()
_seen_view = _UNSEEN
_fading: dict = {}               # native id -> game time to remove it at
_dials_pushed = False
_native_dirty = False
_rebuild_all = False


# ── Seams (monkeypatched by tests) ────────────────────────────────────────────

def _effective_radius(rock) -> float:
    from engine.rocks.rock import effective_radius
    return effective_radius(rock)


def _is_dying(rock) -> bool:
    from engine.rocks import death
    if death.is_dying_rock(rock):
        return True
    try:
        return bool(rock.IsDead())
    except Exception:
        return False


def _game_time() -> float:
    try:
        import App
        return float(App.g_kUtopiaModule.GetGameTime())
    except Exception:
        return 0.0


def _swallow(what: str, e: BaseException) -> None:
    from engine import dev_mode
    dev_mode.log_swallowed("minors " + what, e)


# ── Pure spec builders ────────────────────────────────────────────────────────

def _family_index(name) -> int:
    return md.FAMILY_INDEX.get(name, md.FAMILY_INDEX["silicate"])


def _set_name(pSet) -> str:
    if pSet is None:
        return ""
    try:
        return str(pSet.GetName() or "")
    except Exception:
        return ""


def _halo_numbers(radius: float) -> dict:
    count = int(round(md.get("halo_per_gu2") * radius * radius))
    count = max(md.get("halo_min"), min(md.get("halo_max"), count))
    return dict(
        shell_inner=md.get("halo_inner") * radius,
        shell_outer=md.get("halo_outer") * radius,
        falloff=float(md.get("halo_falloff")),
        count=count,
        r_min=float(md.get("halo_r_min_gu")),
        r_max=min(md.get("halo_r_max_frac") * radius, md.get("halo_r_max_gu")),
        size_exponent=float(md.get("halo_size_exponent")),
    )


def halo_spec(rock, iid) -> Optional[CloudSpec]:
    """A realised rock's halo, or None when it is dying / dead / sizeless."""
    if _is_dying(rock):
        return None
    radius = float(_effective_radius(rock))
    if radius <= 0.0:
        return None
    name = rock.GetName()
    return CloudSpec(
        key="halo:" + name, anchor="instance", instance=iid,
        point=_ZERO, velocity=_ZERO, t0=0.0,
        family=_family_index(rock.__dict__.get("_rock_family", "silicate")),
        seed=zlib.crc32(("halo:" + name).encode("utf-8")),
        orbit_rate=float(md.get("halo_orbit_rate")),
        **_halo_numbers(radius))


def tile_spec(field_obj, view_set, set_name: str, offset: tuple) -> Optional[CloudSpec]:
    """A BC AsteroidField as a uniform sphere of minors, at the field's
    location expressed in VIEW space (`offset` = offset_between(view, set))."""
    tiles = int(field_obj.GetNumTilesPerAxis())
    count = int(round(tiles ** 3 * field_obj.GetNumAsteroidsPerTile()
                      * md.get("tile_count_mult")))
    radius = float(field_obj.GetFieldRadius())
    if count <= 0 or radius <= 0.0:
        return None
    loc = field_obj.GetWorldLocation()
    name = field_obj.GetName()
    key = "tile:%s:%s" % (set_name, name)
    r_min = float(md.get("tile_r_min_gu"))
    return CloudSpec(
        key=key, anchor="point", instance=None,
        point=(loc.x + offset[0], loc.y + offset[1], loc.z + offset[2]),
        velocity=_ZERO, t0=0.0,
        shell_inner=0.0, shell_outer=radius, falloff=0.0, count=count,
        r_min=r_min,
        r_max=max(r_min, md.get("tile_r_per_size_factor")
                  * float(field_obj.GetAsteroidSizeFactor())),
        size_exponent=float(md.get("tile_size_exponent")),
        family=md.FAMILY_INDEX["silicate"],
        seed=zlib.crc32(key.encode("utf-8")),
        orbit_rate=float(md.get("tile_orbit_rate")))


def _free_key(spec: FreeCloudSpec) -> str:
    return "free:%s:%s" % (_set_name(spec.pSet), spec.rock_name)


def _offset(view_set, pSet):
    """offset_between(view, pSet), with a set of None (or the view itself)
    meaning the viewed set: zero."""
    if pSet is None or pSet is view_set:
        return _ZERO
    from engine.systems import frames
    return frames.offset_between(view_set, pSet)


def _free_cloud_spec(spec: FreeCloudSpec, view_set) -> Optional[CloudSpec]:
    off = _offset(view_set, spec.pSet)
    if off is None:
        return None
    radius = float(spec.halo_radius_gu)
    p0 = tuple(float(p) + float(o) for p, o in zip(spec.p0, off))
    return CloudSpec(
        key=_free_key(spec), anchor="free", instance=None,
        point=p0, velocity=tuple(float(c) for c in spec.velocity),
        t0=float(spec.t0),
        family=_family_index(spec.family),
        # The halo's own seed: a re-sent free cloud regenerates the very
        # instances the detached halo carried.
        seed=zlib.crc32(("halo:" + spec.rock_name).encode("utf-8")),
        orbit_rate=0.0,
        debris=tuple(dict(d) for d in spec.debris),
        **_halo_numbers(radius))


def desired_clouds(view_set, rock_instances: dict, fields: list) -> dict:
    """{key: CloudSpec} for the viewed set: a halo per rock, a tile cloud per
    field in the viewed frame, and every free cloud whose set is in it."""
    out: dict = {}
    for rock, iid in rock_instances.items():
        s = halo_spec(rock, iid)
        if s is not None:
            out[s.key] = s
    from engine.systems import frames
    for f in fields:
        if f is None:
            continue
        fset = frames.containing_set(f)
        off = _offset(view_set, fset)
        if off is None:
            continue
        s = tile_spec(f, view_set, _set_name(fset), off)
        if s is not None:
            out[s.key] = s
    for entries in _free.values():
        for e in entries:
            s = _free_cloud_spec(e.spec, view_set)
            if s is not None:
                out[s.key] = s
    return out


# ── Registry ──────────────────────────────────────────────────────────────────

def register_free_cloud(spec: FreeCloudSpec) -> None:
    """Queue a dead rock's free cloud; the next reconcile detaches its halo
    into it (or adds it fresh when no halo is held)."""
    _pending_free.append(spec)


def native_ids() -> dict:
    return dict(_ids)


def live_minor_count() -> int:
    """Minors in the clouds native holds, not counting ones already fading
    out (they are on their way to removal)."""
    return sum(s.count + len(s.debris) for k, s in _specs.items()
               if _ids.get(k) not in _fading)


def on_dials_changed(names) -> None:
    global _native_dirty, _rebuild_all
    names = set(names)
    if names & md.NATIVE_KEYS:
        _native_dirty = True
    if names - md.NATIVE_KEYS:
        _rebuild_all = True


def reset(r=None) -> None:
    """Forget every cloud (mission swap). Native minors_clear also wipes the
    fragment tables, so the memo goes with it."""
    global _next_id, _free_seq, _seen_view, _dials_pushed, _native_dirty
    global _rebuild_all
    _ids.clear()
    _specs.clear()
    _free.clear()
    _pending_free.clear()
    _fragments_loaded.clear()
    _fading.clear()
    _next_id = 1
    _free_seq = 0
    _seen_view = _UNSEEN
    _dials_pushed = False
    _native_dirty = False
    _rebuild_all = False
    if md._on_change is on_dials_changed:
        md.set_on_change(None)
    if r is not None:
        try:
            r.minors_clear()
        except Exception as e:
            _swallow("clear", e)


def _desc(spec: CloudSpec, cid: int, fade_in: bool) -> dict:
    return {
        "id": cid, "anchor": spec.anchor, "instance": spec.instance,
        "point": tuple(spec.point), "velocity": tuple(spec.velocity),
        "t0": spec.t0, "shell_inner": spec.shell_inner,
        "shell_outer": spec.shell_outer, "falloff": spec.falloff,
        "count": spec.count, "r_min": spec.r_min, "r_max": spec.r_max,
        "size_exponent": spec.size_exponent, "family": spec.family,
        "seed": spec.seed, "orbit_rate": spec.orbit_rate,
        "fade_in": bool(fade_in), "debris": [dict(d) for d in spec.debris],
    }


def _drop_free(key: str) -> None:
    for name, entries in list(_free.items()):
        kept = [e for e in entries if e.key != key]
        if kept:
            _free[name] = kept
        else:
            del _free[name]


def _remove(r, key: str, *, evict: bool = False) -> None:
    """Remove a held cloud natively and from the registry. A fading cloud
    (or `evict`) also leaves the free list: it is gone for good."""
    cid = _ids.pop(key)
    _specs.pop(key, None)
    if _fading.pop(cid, None) is not None or evict:
        _drop_free(key)
    try:
        r.minors_remove_cloud(cid)
    except Exception as e:
        _swallow("remove_cloud", e)


def _add(r, spec: CloudSpec, fade_in: bool) -> None:
    global _next_id
    cid = _next_id
    _next_id += 1
    try:
        r.minors_add_cloud(_desc(spec, cid, fade_in))
    except Exception as e:
        _swallow("add_cloud", e)
        return
    _ids[spec.key] = cid
    _specs[spec.key] = spec


def _ensure_fragments(r, families) -> None:
    from engine.rocks import catalogue
    for idx in sorted(families):
        if idx in _fragments_loaded:
            continue
        _fragments_loaded.add(idx)
        fam = _FAMILY_NAME.get(idx, "silicate")
        entries = []
        for rock in catalogue.load():
            if rock.kind != "fragment" or rock.family != fam:
                continue
            if len(rock.lod_paths) < 2:
                continue
            try:
                h0 = r.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
                h1 = r.load_model(rock.lod_paths[1], [], None, decals=None, scale=1.0)
            except Exception as e:
                _swallow("load fragment", e)
                continue
            entries.append((h0, h1, rock.bound_radius_m
                            * catalogue.MODEL_UNITS_PER_METRE))
        try:
            r.minors_set_fragments(idx, entries)
        except Exception as e:
            _swallow("set_fragments", e)


def _drain_pending(r, view_set) -> None:
    global _free_seq
    pending = list(_pending_free)
    _pending_free.clear()
    for spec in pending:
        key = _free_key(spec)
        if key in _ids:                      # a same-named rock died again
            _remove(r, key, evict=True)
        _drop_free(key)
        _free_seq += 1
        _free.setdefault(_set_name(spec.pSet), []).append(
            _FreeEntry(spec=spec, seq=_free_seq, key=key))
        halo_key = "halo:" + spec.rock_name
        if halo_key not in _ids:
            continue                         # the diff adds it fresh
        fs = _free_cloud_spec(spec, view_set)
        if fs is None:
            _remove(r, halo_key)
            continue
        cid = _ids.pop(halo_key)
        _specs.pop(halo_key, None)
        try:
            r.minors_detach(cid, fs.point, fs.velocity, fs.t0,
                            [dict(d) for d in fs.debris])
        except Exception as e:
            _swallow("detach", e)
        _ids[key] = cid
        _specs[key] = fs


def _remove_all(r) -> None:
    for key in list(_ids):
        _remove(r, key)


def _enforce_budget(r, now: float) -> None:
    limit = md.get("max_live_minors")
    seconds = float(md.get("free_cloud_fade_seconds"))
    while live_minor_count() > limit:
        candidates = [e for entries in _free.values() for e in entries
                      if e.key in _ids and _ids[e.key] not in _fading]
        if not candidates:
            return
        oldest = min(candidates, key=lambda e: e.seq)
        cid = _ids[oldest.key]
        _fading[cid] = now + seconds
        try:
            r.minors_fade_out(cid, seconds)
        except Exception as e:
            _swallow("fade_out", e)


def reconcile_with(r, view_set, rock_instances: dict, fields: list,
                   player_iid) -> None:
    """The testable core of `reconcile` (minor-rocks spec §1)."""
    global _seen_view, _dials_pushed, _native_dirty, _rebuild_all
    from engine.rocks import catalogue
    try:
        enabled = bool(r.minors_enabled())
    except Exception as e:
        _swallow("enabled", e)
        enabled = False
    if not catalogue.load() or not enabled:
        _remove_all(r)
        return

    view_key = _set_name(view_set)
    first_of_view = _seen_view is _UNSEEN or _seen_view != view_key
    _seen_view = view_key

    if not _dials_pushed or _native_dirty:
        if not _dials_pushed:
            md.set_on_change(on_dials_changed)
        _dials_pushed = True
        _native_dirty = False
        try:
            r.minors_set_dials(md.native())
        except Exception as e:
            _swallow("set_dials", e)

    now = _game_time()
    for cid, until in list(_fading.items()):
        if now >= until:
            key = next((k for k, v in _ids.items() if v == cid), None)
            if key is None:
                _fading.pop(cid, None)
            else:
                _remove(r, key)

    _drain_pending(r, view_set)

    if _rebuild_all:
        _rebuild_all = False
        _remove_all(r)

    desired = desired_clouds(view_set, rock_instances, fields)
    _ensure_fragments(r, {s.family for s in desired.values()})

    for key in list(_ids):
        want = desired.get(key)
        if want is None or want != _specs.get(key):
            if _ids[key] in _fading:
                desired.pop(key, None)      # mid-eviction: gone for good
            _remove(r, key)
    for key, spec in desired.items():
        if key not in _ids:
            _add(r, spec, fade_in=not first_of_view)

    _enforce_budget(r, now)

    try:
        r.minors_set_player(player_iid)
    except Exception as e:
        _swallow("set_player", e)


def reconcile(session, r) -> None:
    """Per frame, from host_loop._reconcile_scene: the viewed set's rocks
    (realised, not scope-hidden, in the viewed frame) and asteroid fields."""
    try:
        import App
        from engine.rocks.rock import is_rock
        from engine.systems import frames
        view = frames.viewing_set()
        hidden = getattr(session, "scope_hidden", ())
        instances = getattr(session, "ship_instances", {}) or {}
        rocks = {}
        for ship, iid in list(instances.items()):
            if not is_rock(ship) or iid in hidden:
                continue
            if _offset(view, frames.containing_set(ship)) is None:
                continue
            rocks[ship] = iid
        fields = []
        if view is not None:
            for o in view.GetClassObjectList(App.CT_ASTEROID_FIELD):
                f = App.AsteroidField_Cast(o)
                if f is not None:
                    fields.append(f)
        player = getattr(session, "player", None)
        player_iid = instances.get(player) if player is not None else None
    except Exception as e:
        _swallow("gather", e)
        return
    try:
        reconcile_with(r, view, rocks, fields, player_iid)
    except Exception as e:
        _swallow("reconcile", e)
