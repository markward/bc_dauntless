"""The Ship Property Viewer's Decals pane (spec docs/superpowers/specs/
2026-09-28-spv-decal-editing-design.md S3-S4).

A mixin for `ShipPropertyViewerPanel`: the panel owns the camera, the gizmo
input loop, the undo stack and the Save/toast plumbing; this module owns the
decal working list and everything that turns it into a live renderer
override (`host_io.set_instance_decals`) and a `decals.json` write
(`decals_writer.save_decals`).

Frames. Every `Placement` is in the SHIP-BODY frame in NIF units -- the
frame `decals.json` and the shader's `p_body = inverse(inst.world) * pos`
use (the committed Ambassador `top` is ~120 units wide). The render
instance's world is `loc + R * (BC_MODEL_SCALE * GetScale() * p)`, so a GU
is 1 / (0.01 * GetScale()) body units -- NOT 1 / GetScale().

- A hull click: cursor -> `manual_aim.cursor_ray` (SET coords, the exact
  inverse of the SPV projection) -> shifted into VIEW coords ->
  `ray_trace_mesh` -> the VIEW-coord hit straight into the native
  `host_io.world_to_body`, which inverts the renderer's own
  `inst->world_linear` (Ruling O: the one matrix that cannot drift).
- The gizmo, the other way: `body_to_world` through host_loop's own
  `_world_matrix_from(loc, rot, instance_scale(ship))`, and a drag of `t` GU
  along a world gizmo axis is `t / instance_scale(ship)` body units.
"""
from __future__ import annotations

import math
import posixpath
import time
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Tuple

from engine.ui import decal_editor

Vec3 = Tuple[float, float, float]

# Decal maths reference directions in the body frame (BC: +Y forward, +Z up).
BODY_FORWARD: Vec3 = (0.0, 1.0, 0.0)
BODY_UP: Vec3 = (0.0, 0.0, 1.0)
# Height of a new placement without a mask PNG: 2:1, the usual registry strip.
DEFAULT_MASK_ASPECT = 2.0
# Spec S2.4a: up to 16 placements (projectors) per model, sharing up to 4
# DISTINCT masks (texture units 8..11) -- native kMaxDecals / kMaxDecalMasks
# and hull_decals' _MAX_DECALS / _MAX_DECAL_MASKS.
MAX_DECALS = 16
MAX_DECAL_MASKS = 4
def _is_registry_folder(folder: Path) -> bool:
    """A registry folder holds PNG masks, or nothing yet (a new registry
    previews the checkerboard). A folder holding files but no PNG is
    artwork sources (e.g. `templates/` of SVGs), not a registry."""
    try:
        files = [f for f in folder.iterdir() if f.is_file()]
    except OSError:
        return False
    return not files or any(f.suffix.lower() == ".png" for f in files)


# While the pane is open the override is re-pushed at least this often, even
# unchanged, so the native mask cache sees a PNG re-exported from Gimp
# (Ruling K: it reloads on an mtime change, checked at push time).
OVERRIDE_REFRESH_S = 1.0
MISS_HINT = "Missed the hull -- click on the ship"
CAP_HINT = "At most %d decals per ship -- delete one first" % MAX_DECALS
# %s = the masks already in use (any of which can still be picked).
MASK_CAP_HINT = ("At most %d distinct masks per ship -- reuse one of: "
                 % MAX_DECAL_MASKS) + "%s"
# Persistent while the preview falls back to a registry the game would never
# pick (no ID swap, no default_registry): the game draws NO decals then.
NOT_IN_GAME_HINT = ("Not shown in game — no registry for this ship. "
                    "Use 'Make X the class default'.")
MIN_DEPTH = 1e-4
# The top-right tool panels' steppers are authored for hardpoints (+-0.01 /
# +-0.1 body GU). A decal's numbers are NIF units (1 GU = 1 / BC_MODEL_SCALE
# of them), so the JS multiplies -- and relabels -- a decal's steps by
# `step_scale`: Move and Width then step the same physical distance as on a
# hardpoint; Depth (a few units deep) steps a tenth of that.
DEPTH_STEP_SCALE = 10.0


def placeholder_path() -> Path:
    """The checkerboard preview for a placement whose registry has no PNG.
    A PROJECT asset (like scuff_normal.tga), resolved at use."""
    from engine import paths
    return paths.project_asset_root() / "textures" / "decal_placeholder.png"


def png_aspect(path) -> Optional[float]:
    """width / height from a PNG's IHDR, or None if `path` isn't a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w = int.from_bytes(head[16:20], "big")
    h = int.from_bytes(head[20:24], "big")
    if w <= 0 or h <= 0:
        return None
    return w / h


def instance_scale(ship) -> float:
    """The render instance's uniform scale: BC_MODEL_SCALE (NIF units -> GU)
    times the script's GetScale() -- the factor host_loop realises every ship
    instance with (`_ship_world_matrix(ship, BC_MODEL_SCALE)`)."""
    from engine.host_loop import BC_MODEL_SCALE
    try:
        s = float(ship.GetScale())
    except Exception:
        s = 1.0
    return BC_MODEL_SCALE * (s if s > 1e-9 else 1.0)


def _instance_matrix(ship) -> list:
    """The instance's row-major world matrix, built by host_loop's own
    `_world_matrix_from` (imported, never re-derived) in the ship's SET
    coordinates."""
    from engine.appc.math import TGMatrix3
    from engine.host_loop import _world_matrix_from
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
    if not isinstance(rot, TGMatrix3):
        rot = TGMatrix3()
    return _world_matrix_from(ship.GetWorldLocation(), rot, instance_scale(ship))


def body_to_world(ship, p: Vec3) -> Vec3:
    """Body point (NIF units) -> set-coordinate world point, through the
    instance matrix. The inverse of what `host_io.world_to_body` does
    natively for a hull hit."""
    m = _instance_matrix(ship)
    return tuple(m[4 * r] * p[0] + m[4 * r + 1] * p[1] + m[4 * r + 2] * p[2]
                 + m[4 * r + 3] for r in range(3))


def body_dir_to_world(ship, v: Vec3) -> Vec3:
    """Body direction -> unit world direction (the instance's linear part,
    renormalised, so the uniform scale drops out)."""
    m = _instance_matrix(ship)
    return _unit(tuple(m[4 * r] * v[0] + m[4 * r + 1] * v[1] + m[4 * r + 2] * v[2]
                       for r in range(3)))


def _unit(v: Vec3) -> Vec3:
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


class DecalsPaneMixin:
    """Decals pane state and behaviour. See the module docstring."""

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _decal_reset_state(self) -> None:
        self._decals_active = False           # the pane is the active one
        self._decal_prev_hull = False         # show_hull_texture before entering
        self._decal_model_rel: Optional[str] = None
        # The staged list (None until the pane first loads it this session)
        # and what is on disk; dirty = they differ.
        self._decal_working: Optional[List[decal_editor.Placement]] = None
        self._decal_baseline: List[decal_editor.Placement] = []
        self._decal_default: Optional[str] = None
        self._decal_baseline_default: Optional[str] = None
        # Entries under "decals" that don't parse into a Placement, raw JSON
        # value by name: listed "(unreadable)", deletable, never editable,
        # and written back unchanged on Save (never destroy data silently).
        self._decal_passthrough: dict = {}
        self._decal_baseline_passthrough: dict = {}
        # The registry the SHIP picks by its own ID ReplaceTexture (None when
        # it queues none) -- with the staged default, what the game would use.
        self._decal_id_registry: Optional[str] = None
        self._decal_registries: List[str] = []
        self._decal_registry: Optional[str] = None
        self._decal_selected: Optional[str] = None
        self._decal_adding: Optional[str] = None   # name awaiting a hull click
        self._decal_adding_mask: str = ""          # ... and the mask it uses
        self._decal_reposition = False
        self._decal_error: Optional[str] = None
        self._decal_grab: Optional[decal_editor.Placement] = None
        # What the renderer holds: the iid an override was pushed to (None =
        # nothing to clear) and the last (iid, entries) pushed.
        self._decal_override_iid = None
        self._decal_last_push = None
        self._decal_last_push_time = 0.0

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def _decal_dir(self) -> Optional[str]:
        rel = self._decal_model_rel
        return posixpath.dirname(rel) if rel else None

    def _decal_iid(self):
        if self._iid_getter is None:
            return None
        try:
            return self._iid_getter()
        except Exception:
            return None

    def _decal_names(self) -> List[str]:
        return [p.name for p in (self._decal_working or [])]

    def _decal_taken_names(self) -> List[str]:
        """Every declared name, parsed or unreadable: a new placement may
        not shadow either (they share one JSON object)."""
        return self._decal_names() + list(self._decal_passthrough)

    def _decal_count(self) -> int:
        """Declared placements, unreadable ones included -- the game's
        16-cap truncates the file's entries, readable or not."""
        return len(self._decal_working or []) + len(self._decal_passthrough)

    def _decal_used_masks(self) -> List[str]:
        """The distinct mask stems the readable placements use, first-use
        order. Counted by exact stem within the one previewed registry, the
        same identity native and hull_decals dedupe by (the resolved path).

        - A stem with NO PNG yet still counts: the pane previews it with
          the checkerboard, and once authored it takes a slot, so the pane
          never lets Mark stage a list the game would then truncate.
        - Unreadable (passthrough) placements count toward the 16-cap but
          NOT toward the masks: their mask is unknown, and the game skips an
          unreadable entry before it reaches the mask cap."""
        out: List[str] = []
        for p in self._decal_working or []:
            m = decal_editor.mask_of(p)
            if m not in out:
                out.append(m)
        return out

    def _decal_auto_name(self, mask: str) -> str:
        """Spec S2.4a: the mask's own name if free, else `<mask>_2`,
        `<mask>_3`, ... -- free = valid_name accepts it against every taken
        name (case-folded, unreadable ones included)."""
        taken = self._decal_taken_names()
        name, k = mask, 2
        while decal_editor.valid_name(name, taken) is not None:
            name, k = "%s_%d" % (mask, k), k + 1
        return name

    def _decal_index(self, name) -> Optional[int]:
        for i, p in enumerate(self._decal_working or []):
            if p.name == name:
                return i
        return None

    def _decal_scan_registries(self) -> List[str]:
        """Registry folders under the class's Masks/, across the replacements
        overlay, installed mods and the stock tree (case-folded, sorted). A
        folder holding files but no PNG (e.g. `templates/` of SVG sources)
        is not a registry; an empty one is (see `_is_registry_folder`)."""
        from engine import paths
        d = self._decal_dir()
        if d is None:
            return []
        names = {}
        for masks in paths.game_asset_dirs(f"{d}/Masks"):
            try:
                children = sorted(masks.iterdir()) if masks.is_dir() else []
            except OSError:
                children = []
            for c in children:
                if c.is_dir() and _is_registry_folder(c):
                    names.setdefault(c.name.lower(), c.name)
        return sorted(names.values(), key=str.lower)

    def _decal_mask_path(self, mask: str) -> Optional[Path]:
        """The previewed registry's PNG for mask stem `mask`, or None. Pass
        `decal_editor.mask_of(p)` for a placement, never `p.name`."""
        from engine import paths
        d, reg = self._decal_dir(), self._decal_registry
        if d is None or not reg:
            return None
        p = paths.game_asset(f"{d}/Masks/{reg}/{mask}.png")
        return p if p.is_file() else None

    def _decal_aspect(self, mask: str) -> float:
        """width / height of mask stem `mask`'s PNG, else 2:1."""
        m = self._decal_mask_path(mask)
        a = png_aspect(m) if m is not None else None
        return a if a is not None else DEFAULT_MASK_ASPECT

    def _decal_ship_radius(self, ship) -> float:
        """The ship's radius in body (NIF) units, the placement frame: the
        model's own bounds (|aabb centre| + |half extents|, host_loop's
        `_model_extent_from_aabb`, the same extent realize derives a missing
        radius from) when the instance has a model; else GetRadius(), which
        is UNSCALED GU, over BC_MODEL_SCALE -- never divided by GetScale()."""
        from engine import host_io
        from engine.host_loop import BC_MODEL_SCALE, _model_extent_from_aabb
        iid = self._decal_iid()
        if iid is not None:
            try:
                handle = host_io.instance_model(iid)
                if handle:
                    from engine import renderer
                    c, he = renderer.model_aabb(handle)
                    r = _model_extent_from_aabb(c, he)
                    if r > 0.0:
                        return r
            except Exception:
                pass
        r = float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 0.0
        r /= BC_MODEL_SCALE
        return r if r > 0.0 else 1.0

    def _decal_refresh_registries(self) -> None:
        """Rescan the overlay (a PNG or registry folder authored in Gimp since
        the last scan must show) and the registry list."""
        from engine import mods
        mods.invalidate_replacements()
        self._decal_registries = self._decal_scan_registries()

    def _decal_load(self) -> None:
        """Load the class's declared placements into the working list."""
        from engine.appc import hull_decals, registry_texture
        ship = self._ship_getter()
        rel = None
        if self._model_rel_getter is not None and ship is not None:
            try:
                rel = self._model_rel_getter(ship)
            except Exception:
                rel = None
        self._decal_model_rel = rel or None
        self._decal_refresh_registries()
        working, passthrough, default, doc = [], {}, None, None
        d = self._decal_dir()
        if d is not None:
            doc = hull_decals.load_decals_doc(d)
        if isinstance(doc, dict):
            dr = doc.get("default_registry")
            default = dr if isinstance(dr, str) and dr else None
            decals = doc.get("decals")
            for name, entry in (decals.items() if isinstance(decals, dict) else []):
                try:
                    working.append(decal_editor.from_json_entry(name, entry))
                except (KeyError, TypeError, ValueError, AttributeError):
                    passthrough[name] = entry
        self._decal_working = working
        self._decal_baseline = list(working)
        self._decal_passthrough = passthrough
        self._decal_baseline_passthrough = dict(passthrough)
        self._decal_default = default
        self._decal_baseline_default = default
        reps = registry_texture.replacements_for(ship) if ship is not None else []
        self._decal_id_registry = hull_decals.registry_stem(reps)
        reg = hull_decals.resolve_registry(
            reps, doc if isinstance(doc, dict) else None)
        if reg is None and self._decal_registries:
            # Something to preview -- flagged by NOT_IN_GAME_HINT (_decal_hint).
            reg = self._decal_registries[0]
        self._decal_registry = reg

    def _decal_hint(self) -> Optional[str]:
        """NOT_IN_GAME_HINT while the game would resolve no registry for this
        ship (no ID swap, no staged class default) yet the pane previews one."""
        if (self._decal_registry and self._decal_id_registry is None
                and not self._decal_default):
            return NOT_IN_GAME_HINT
        return None

    def _decal_dirty(self) -> bool:
        return (self._decal_working is not None
                and (self._decal_working != self._decal_baseline
                     or self._decal_passthrough != self._decal_baseline_passthrough
                     or self._decal_default != self._decal_baseline_default))

    def _decal_change_count(self) -> int:
        if not self._decal_dirty():
            return 0
        base = {p.name: p for p in self._decal_baseline}
        work = {p.name: p for p in self._decal_working}
        n = sum(1 for k in set(base) | set(work) if base.get(k) != work.get(k))
        n += len(set(self._decal_baseline_passthrough) ^ set(self._decal_passthrough))
        if self._decal_default != self._decal_baseline_default:
            n += 1
        return max(n, 1)

    # ------------------------------------------------------------------
    # The live override
    # ------------------------------------------------------------------
    def _decal_entries(self) -> list:
        out = []
        for p in (self._decal_working or [])[:MAX_DECALS]:
            mask = (self._decal_mask_path(decal_editor.mask_of(p))
                    or placeholder_path())
            out.append((p.shape,
                        tuple(float(c) for c in p.origin),
                        tuple(float(c) for c in p.u_axis),
                        tuple(float(c) for c in p.v_axis),
                        tuple(float(c) for c in p.normal),
                        float(p.depth), str(mask)))
        return out

    def _decal_sync_override(self, force: bool = False) -> None:
        """Push the working list as the SPV instance's decal override when it
        (or the previewed registry) changed, or when `force`d."""
        if not self._decals_active or self._decal_working is None:
            return
        iid = self._decal_iid()
        if iid is None:
            return
        if self._decal_override_iid is not None and self._decal_override_iid != iid:
            # The instance changed under a live override (a respawn): give
            # the old one its baked decals back before previewing on the new.
            self._decal_clear_override()
        entries = self._decal_entries()
        key = (iid, entries)
        if not force and key == self._decal_last_push:
            return
        from engine import host_io
        try:
            host_io.set_instance_decals(iid, entries)
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv set_instance_decals", e)
            return
        self._decal_override_iid = iid
        self._decal_last_push = key
        self._decal_last_push_time = time.monotonic()

    def _decal_clear_override(self) -> None:
        iid = self._decal_override_iid
        self._decal_override_iid = None
        self._decal_last_push = None
        if iid is None:
            return
        from engine import host_io
        try:
            host_io.set_instance_decals(iid, None)
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv clear instance decals", e)

    def _decal_refresh_tick(self) -> None:
        """Per-frame (handle_input): re-push periodically so a re-exported
        mask reloads natively (Ruling K)."""
        if (self._decals_active and self._decal_override_iid is not None
                and time.monotonic() - self._decal_last_push_time
                >= OVERRIDE_REFRESH_S):
            self._decal_sync_override(force=True)

    def on_mission_swap(self) -> None:
        """The mission is being torn down: drop the override (its instance is
        about to die) and every decal edit with it."""
        self._decal_clear_override()
        if self._decals_active:
            self.show_hull_texture = self._decal_prev_hull
        self._decal_reset_state()
        self._last_pushed = None

    # ------------------------------------------------------------------
    # Enter / leave
    # ------------------------------------------------------------------
    def _decal_enter(self) -> None:
        self._decals_active = True
        self._decal_prev_hull = self.show_hull_texture
        self.show_hull_texture = True       # the hologram cannot show decals
        if self._decal_working is None:
            self._decal_load()
        else:
            self._decal_refresh_registries()

    def _decal_leave(self) -> None:
        self._decal_clear_override()
        self._decals_active = False
        self.show_hull_texture = self._decal_prev_hull
        self._decal_adding = None
        self._decal_adding_mask = ""
        self._decal_reposition = False
        self._decal_error = None
        self._decal_grab = None
        if self._decal_dirty():
            self._show_toast("Decal edits are not saved yet -- Save to keep them")

    # ------------------------------------------------------------------
    # Actions (routed from _dispatch_event_inner)
    # ------------------------------------------------------------------
    def _dispatch_decal_action(self, action: str) -> bool:
        self._last_pushed = None
        if action == "decal-pane":
            if self._decals_active:
                self._decal_leave()
            else:
                self._decal_enter()
            return True
        if not self._decals_active or self._decal_working is None:
            return False
        verb, _, arg = action.partition(":")
        if verb == "decal-select":
            if self._decal_index(arg) is None:
                return False
            self._decal_selected = None if self._decal_selected == arg else arg
            if self._decal_selected is not None:
                self.selected_index = None
                self._selected_light_index = None
                self._selected_emitter = None
                from engine.ui import ship_property_viewer as _spv
                _spv.select_model_part(None, self._model_part_nodes)
            self._decal_reposition = False
            self._decal_error = None
            return True
        if verb == "decal-add":
            # `arg` is the MASK stem; the placement name is derived from it.
            self._decal_reposition = False
            self._decal_adding, self._decal_adding_mask = None, ""
            if self._decal_count() >= MAX_DECALS:
                self._decal_error = CAP_HINT
                return True
            err = decal_editor.valid_name(arg, ())
            if err is not None:
                self._decal_error = "Mask refused: " + err
                return True
            used = self._decal_used_masks()
            if arg not in used and len(used) >= MAX_DECAL_MASKS:
                self._decal_error = MASK_CAP_HINT % ", ".join(used)
                return True
            self._decal_adding = self._decal_auto_name(arg)
            self._decal_adding_mask = arg
            self._decal_error = None
            return True
        if verb == "decal-add-cancel":
            self._decal_adding = None
            self._decal_adding_mask = ""
            self._decal_error = None
            return True
        if verb == "decal-delete":
            if arg in self._decal_passthrough:
                del self._decal_passthrough[arg]
                self._decal_error = None
                return True
            i = self._decal_index(arg)
            if i is None:
                return False
            del self._decal_working[i]
            if self._decal_selected == arg:
                self._decal_selected = None
                self._decal_reposition = False
            self._decal_error = None
            return True
        if verb == "decal-registry":
            self._decal_refresh_registries()
            if arg not in self._decal_registries:
                return False
            self._decal_registry = arg
            self._decal_error = None
            return True
        if verb == "decal-default":
            # Membership, not valid_name: a registry is a FOLDER, and a
            # folder name may carry spaces or dots. "" clears the default.
            if arg:
                self._decal_refresh_registries()
                if arg not in self._decal_registries:
                    self._decal_error = ("No registry folder %r under Masks/" % arg)
                    return True
            self._decal_default = arg or None
            self._decal_error = None
            return True
        if verb == "decal-reposition":
            if self._decal_selected is None:
                return False
            self._decal_reposition = not self._decal_reposition
            self._decal_adding = None
            return True
        return False

    # ------------------------------------------------------------------
    # Hull clicks
    # ------------------------------------------------------------------
    def _decal_hull_hit(self, x, y, viewport):
        """(body point, body normal) under the cursor on the SPV instance's
        hull, or None on a miss. See the module docstring for the frames."""
        ship, iid, cam = self._ship_getter(), self._decal_iid(), self.camera
        if ship is None or iid is None or cam is None:
            return None
        from engine import host_io
        from engine.appc.math import TGPoint3
        from engine.manual_aim import cursor_ray
        from engine.systems import frames
        ray = cursor_ray((x, y), viewport, cam)
        if ray is None:
            return None
        origin, direction = ray
        off = frames.view_offset(frames.containing_set(ship))
        o = frames.shifted(TGPoint3(*origin), off, 1.0)
        try:
            hit = host_io.ray_trace_mesh(iid, (o.x, o.y, o.z), direction, cam.far)
        except Exception:
            hit = None
        if hit is None:
            return None
        (px, py, pz), normal, _t = hit
        # The hit is in VIEW coordinates, which is what world_to_body takes
        # (the host_io Python wrapper subtracts the instance translation,
        # then the native call inverts the instance's own world_linear).
        try:
            body = host_io.world_to_body(iid, (px, py, pz), tuple(normal))
        except Exception:
            body = None
        if body is None:
            return None
        pb, nb = body
        return tuple(float(c) for c in pb), _unit(tuple(float(c) for c in nb))

    def decal_click(self, x, y, viewport) -> bool:
        """A viewport click while the Decals pane is active. Places the
        pending Add, or re-seats the selection under Reposition. True when
        the click belonged to the pane (it never falls through to a pin
        pick while the pane is active)."""
        if not self._decals_active or self._decal_working is None:
            return False
        if self._decal_adding is None and not self._decal_reposition:
            return True
        before = self._snapshot_pending()
        self._last_pushed = None
        hit = self._decal_hull_hit(x, y, viewport)
        if hit is None:
            self._decal_error = MISS_HINT
            return True
        pb, nb = hit
        try:
            if self._decal_adding is not None:
                name = self._decal_adding
                mask = self._decal_adding_mask or name
                p = decal_editor.place_at_hit(
                    name, pb, nb, BODY_FORWARD, BODY_UP,
                    self._decal_ship_radius(self._ship_getter()),
                    self._decal_aspect(mask))
                # "" when the name IS the mask: no redundant "mask" key.
                self._decal_working.append(
                    replace(p, mask="" if mask == name else mask))
                self._decal_selected = name
                self._decal_adding = None
                self._decal_adding_mask = ""
            else:
                i = self._decal_index(self._decal_selected)
                if i is None:
                    self._decal_reposition = False
                    return True
                self._decal_working[i] = decal_editor.reposition(
                    self._decal_working[i], pb, nb, BODY_FORWARD, BODY_UP)
                self._decal_reposition = False
        except ValueError as e:
            self._decal_error = "Cannot place there: %s" % e
            return True
        self._decal_error = None
        if before != self._snapshot_pending():
            self._undo_stack.append(before)
        self._decal_sync_override()
        return True

    # ------------------------------------------------------------------
    # Gizmo (Move = u/v arrows, Rotate = ring about the normal, Scale)
    # ------------------------------------------------------------------
    def _decal_target(self) -> Optional[decal_editor.Placement]:
        if not self._decals_active:
            return None
        i = self._decal_index(self._decal_selected)
        return self._decal_working[i] if i is not None else None

    def _decal_by_name(self, name) -> Optional[decal_editor.Placement]:
        """The working placement called `name`, or None."""
        i = self._decal_index(name)
        return self._decal_working[i] if i is not None else None

    def _decal_apply(self, new_p) -> None:
        """Replace the selected placement with `new_p` and re-push the
        override (every `DecalTarget` edit lands here)."""
        i = self._decal_index(self._decal_selected)
        if i is None:
            return
        self._decal_working[i] = new_p
        self._last_pushed = None
        self._decal_sync_override()

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def _decal_state_key(self) -> tuple:
        return (self._decals_active,
                tuple(self._decal_working) if self._decal_working is not None else None,
                tuple(self._decal_passthrough),
                self._decal_registry, self._decal_default,
                tuple(self._decal_registries), self._decal_selected,
                self._decal_adding, self._decal_adding_mask,
                self._decal_reposition, self._decal_error)

    def _decal_suggested_names(self) -> List[str]:
        """MASKS the Add picker offers: every PNG stem in the previewed
        registry -- placed or not, a mask is reusable (S2.4a) -- and nothing
        else (Mark: only real files, no stock suggestions). Keyboard -> CEF
        forwarding does not exist, so the MASK is picked and the placement
        name is derived from it. Valid stems only, case-folded dedupe."""
        from engine import paths
        out: List[str] = []
        d, reg = self._decal_dir(), self._decal_registry
        if d is not None and reg:
            for folder in paths.game_asset_dirs(f"{d}/Masks/{reg}"):
                try:
                    files = sorted(folder.iterdir()) if folder.is_dir() else []
                except OSError:
                    files = []
                for f in files:
                    if f.suffix.lower() == ".png":
                        out.append(f.stem)
        seen, result = set(), []
        for n in out:
            if n.lower() in seen:
                continue
            seen.add(n.lower())
            if decal_editor.valid_name(n, ()) is None:
                result.append(n)
        return result

    # ------------------------------------------------------------------
    # The top-right tool panels. A selected decal drives them (and the
    # gizmo) through `spv_edit_targets.DecalTarget`; its steppers step in GU.
    # ------------------------------------------------------------------
    @staticmethod
    def _decal_coord_step_scale() -> float:
        from engine.host_loop import BC_MODEL_SCALE
        return 1.0 / BC_MODEL_SCALE

    def _decals_payload(self) -> dict:
        working = self._decal_working or []
        return {
            "active": self._decals_active,
            "has_model": self._decal_model_rel is not None,
            "registries": list(self._decal_registries),
            "registry": self._decal_registry,
            "default_registry": self._decal_default,
            "placements": [{"name": p.name,
                            "has_mask": self._decal_mask_path(
                                decal_editor.mask_of(p)) is not None,
                            "mask": decal_editor.mask_of(p)}
                           for p in working]
                          + [{"name": n, "has_mask": False, "unreadable": True}
                             for n in self._decal_passthrough],
            "selected": self._decal_selected,
            "adding": self._decal_adding is not None,
            "adding_name": self._decal_adding,
            "reposition": self._decal_reposition,
            "error": self._decal_error,
            "hint": self._decal_hint(),
            "can_add": self._decal_count() < MAX_DECALS,
            "max_decals": MAX_DECALS,
            "suggested_names": (self._decal_suggested_names()
                                if self._decals_active else []),
            "dirty": self._decal_dirty(),
        }

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _decal_save(self) -> bool:
        """Write the working list. False (toast shown, edits kept) on failure."""
        from engine.appc import decals_writer
        if self._decal_model_rel is None:
            self._show_toast("Decal save failed: this ship declares no model path")
            return False
        try:
            path = decals_writer.save_decals(
                self._decal_model_rel, list(self._decal_working), self._decal_default,
                passthrough=dict(self._decal_passthrough))
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv decal save", e)
            self._show_toast("Decal save failed: %s" % e)
            return False
        self._decal_baseline = list(self._decal_working)
        self._decal_baseline_passthrough = dict(self._decal_passthrough)
        self._decal_baseline_default = self._decal_default
        self._show_toast("Saved decals to %s" % path)
        return True
