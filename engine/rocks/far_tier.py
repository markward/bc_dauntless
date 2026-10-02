"""What the far tier draws for the viewed set (far-tier plan Task 10).

Python owns the INPUTS; native (renderer.far_*) owns the field. Every frame
`reconcile_with` pushes, each only when it changed:

  far_set_catalogue   once per catalogue root (impostor atlases + view dirs;
                      kind/family/bound and, for the near band's silicate
                      fragments and majors, lod0/lod1 model handles)
  far_set_dials       once, and again on a far_dials NATIVE-key change
  far_set_frame       EVERY frame -- the anchor moves on a region hand-off
  far_set_sources     on a system change, a change in the viewed set's tile
                      sphere sources (set or field list), or a Python-owned
                      far_dials change (population + disc-shape + tile_haze
                      + haze_brightness keys feed density.to_native). Belts (system frame)
                      first, then one view-space sphere per AsteroidField in
                      the viewed set (tile-field haze, added 2026-10-02).
  far_set_rocks       the flagged mission/breakup rocks, when the list changes

A rock is flagged by `note_model` at realise time, with the model path and
scale that were ACTUALLY loaded: a catalogue rock carries its catalogue index
(impostor) and bound radius; a stock asteroid NIF (the catalogue-off or
failed-load fallback) carries index -1 and the stock mesh's radius.

Every native call is wrapped: rendering can never break the frame. Nothing
here reads a path or the catalogue at import.
"""
from __future__ import annotations

from engine.rocks import far_dials as fd

_ZERO = (0.0, 0.0, 0.0)
_UNSET = object()

# ── Module state (all cleared by reset) ───────────────────────────────────────
_models: dict = {}               # rock -> (catalogue index, radius_mu)
_catalogue_root = None           # root whose catalogue native holds
_dials_pushed = False
_dials_dirty = False
_sources_dirty = False
_system = _UNSET                 # system whose sources native holds
_tiles = _UNSET                  # the tile DiscSources native holds
_rocks_pushed = _UNSET           # the last far_set_rocks list


def _swallow(what: str, e: BaseException) -> None:
    from engine import dev_mode
    dev_mode.log_swallowed("far_tier " + what, e)


# ── Flagging ──────────────────────────────────────────────────────────────────

def note_model(ship, model_path: str, model_scale: float) -> None:
    """Record a realised rock's model. A catalogue rock -> (index, bound
    radius in model units x load scale); a stock asteroid NIF under the
    configured game root -> (-1, STOCK_RADIUS_MU). Anything else (a non-rock,
    a mod's own rock mesh, even one named like a stock NIF) is not recorded,
    and forgets an earlier note for the same ship."""
    from engine.rocks import catalogue
    from engine.rocks.rock import is_rock
    if not is_rock(ship):
        return
    idx = catalogue.index_of_path(model_path)
    if idx >= 0:
        rock = catalogue.load()[idx]
        _models[ship] = (idx, rock.bound_radius_m
                         * catalogue.MODEL_UNITS_PER_METRE * float(model_scale))
        return
    # Only a genuine stock NIF under the configured game root has the stock
    # radius; a mod's same-named mesh is its own size (R13's rule).
    stock = catalogue.stock_key(model_path)
    if stock is not None and catalogue._under_game_root(model_path):
        _models[ship] = (-1, catalogue.STOCK_RADIUS_MU[stock])
        return
    _models.pop(ship, None)


def desired_rocks(rock_instances: dict) -> list:
    """[{"instance", "index", "radius_mu"}] for the noted rocks among
    `rock_instances`, in its (insertion) order."""
    out = []
    for rock, iid in rock_instances.items():
        m = _models.get(rock)
        if m is not None:
            out.append({"instance": iid, "index": m[0], "radius_mu": m[1]})
    return out


def frame_for(view_set) -> tuple:
    """(system name, the viewed region's anchor_gu) for a mapped region;
    (None, origin) for the warp set, a one-set frame (Multi*, Starbase 12,
    QuickBattle) and None. There no BELT is pushed; the viewed set's tile
    haze (view-space spheres) and flagged rocks still draw."""
    from engine.systems import frames
    f = frames.frame_of(view_set)
    if f is None or f.key[0] != "system":
        return None, _ZERO
    return str(f.key[1]), tuple(float(c) for c in f.anchor_gu)


# ── Registry ──────────────────────────────────────────────────────────────────

def on_dials_changed(names) -> None:
    """A native key re-pushes the dials; any other (population / disc
    shape, read by density.to_native) re-pushes the sources."""
    global _dials_dirty, _sources_dirty
    names = set(names)
    if names & fd.NATIVE_KEYS:
        _dials_dirty = True
    if names - fd.NATIVE_KEYS:
        _sources_dirty = True


def reset(r=None) -> None:
    """Forget everything (mission swap); r.far_clear() when given."""
    global _catalogue_root, _dials_pushed, _dials_dirty, _sources_dirty
    global _system, _rocks_pushed, _tiles
    _models.clear()
    _catalogue_root = None
    _dials_pushed = False
    _dials_dirty = False
    _sources_dirty = False
    _system = _UNSET
    _tiles = _UNSET
    _rocks_pushed = _UNSET
    if fd.on_change() is on_dials_changed:
        fd.set_on_change(None)
    if r is not None:
        try:
            r.far_clear()
        except Exception as e:
            _swallow("clear", e)


# The near band (rock fields) streams these: silicate fragments (small) and
# majors (large). Only they get mesh handles.
_NEAR_FAMILY = "silicate"
_NEAR_KINDS = ("fragment", "major")


def _catalogue_entry(r, rock) -> dict:
    """One far_set_catalogue entry. A near-band rock (silicate fragment or
    major with two LODs) also carries lod0/lod1 model handles, loaded exactly
    as minors._ensure_fragments loads fragments; a failed load omits them
    (the host then leaves that rock out of the near band)."""
    from engine.rocks import catalogue
    e = {"albedo": rock.impostor_albedo, "normal": rock.impostor_normal,
         "avg_albedo": tuple(rock.avg_albedo), "kind": rock.kind,
         "family": rock.family,
         "bound_radius_mu": rock.bound_radius_m * catalogue.MODEL_UNITS_PER_METRE}
    if (rock.family == _NEAR_FAMILY and rock.kind in _NEAR_KINDS
            and len(rock.lod_paths) >= 2):
        try:
            e["lod0"] = r.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
            e["lod1"] = r.load_model(rock.lod_paths[1], [], None, decals=None, scale=1.0)
        except Exception as ex:
            _swallow("load near rock", ex)
            e.pop("lod0", None)
    return e


def _push_catalogue(r) -> None:
    global _catalogue_root
    from engine.rocks import catalogue
    root = str(catalogue.catalogue_root())
    if root == _catalogue_root:
        return
    try:
        entries = [_catalogue_entry(r, rock) for rock in catalogue.load()]
        r.far_set_catalogue(entries, [tuple(d) for d in catalogue.impostor_view_dirs()])
    except Exception as e:
        _swallow("set_catalogue", e)
        return
    _catalogue_root = root   # pushed: only now, so a failure is retried


def _push_dials(r) -> None:
    global _dials_pushed, _dials_dirty
    if _dials_pushed and not _dials_dirty:
        return
    if not _dials_pushed:
        fd.set_on_change(on_dials_changed)
    _dials_pushed = True
    _dials_dirty = False
    try:
        r.far_set_dials(fd.native())
    except Exception as e:
        _swallow("set_dials", e)


def tile_sources(view_set, fields) -> list:
    """One sphere DiscSource per AsteroidField of `fields` that lies in
    `view_set` (a field whose containing set is another set: none), centred
    in view space -- so an unmapped set (Multi7) hazes too."""
    from engine.rocks import density, minors
    from engine.systems import frames
    out = []
    for f in fields:
        if f is None:
            continue
        fset = frames.containing_set(f)
        if fset is not None and fset is not view_set:
            continue
        s = density.tile_field_source(f, view_set, minors._set_name(fset or view_set),
                                      _ZERO)
        if s is not None:
            out.append(s)
    return out


def _push_sources(r, system, tiles) -> None:
    global _system, _sources_dirty, _tiles
    if system == _system and tiles == _tiles and not _sources_dirty:
        return
    _system = system
    _tiles = tiles
    _sources_dirty = False
    try:
        from engine.rocks import density
        belts = density.sources_for_system(system) if system else []
        r.far_set_sources([density.to_native(s) for s in belts + list(tiles)])
    except Exception as e:
        _swallow("set_sources", e)


def reconcile_with(r, view_set, rock_instances: dict, fields=()) -> None:
    """The testable core of `reconcile` (far-tier plan Task 10). `fields`:
    the viewed set's AsteroidFields (tile-field haze)."""
    global _rocks_pushed
    _push_catalogue(r)
    _push_dials(r)
    system, anchor = frame_for(view_set)
    try:
        r.far_set_frame(system, anchor)
    except Exception as e:
        _swallow("set_frame", e)
    try:
        tiles = tile_sources(view_set, fields)
    except Exception as e:
        _swallow("tile_sources", e)
        tiles = []
    _push_sources(r, system, tiles)
    rocks = desired_rocks(rock_instances)
    if rocks != _rocks_pushed:
        _rocks_pushed = rocks
        try:
            r.far_set_rocks(rocks)
        except Exception as e:
            _swallow("set_rocks", e)


def reconcile(session, r) -> None:
    """Per frame, from host_loop._reconcile_scene: the viewed set's rocks
    (realised, not scope-hidden, in the viewed frame) and AsteroidFields --
    gathered exactly as minors.reconcile does. Never raises."""
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
            pSet = frames.containing_set(ship)
            if (pSet is not None and pSet is not view
                    and frames.offset_between(view, pSet) is None):
                continue
            rocks[ship] = iid
    except Exception as e:
        _swallow("gather", e)
        return
    # Fields in their own try: a failure costs only the tile haze, never
    # the frame or rock pushes.
    fields = []
    try:
        if view is not None:
            for o in view.GetClassObjectList(App.CT_ASTEROID_FIELD):
                f = App.AsteroidField_Cast(o)
                if f is not None:
                    fields.append(f)
    except Exception as e:
        _swallow("gather fields", e)
        fields = []
    try:
        reconcile_with(r, view, rocks, fields)
    except Exception as e:
        _swallow("reconcile", e)
