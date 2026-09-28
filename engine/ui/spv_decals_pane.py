"""The Ship Property Viewer's Decals pane (spec docs/superpowers/specs/
2026-09-28-spv-decal-editing-design.md S3-S4).

A mixin for `ShipPropertyViewerPanel`: the panel owns the camera, the gizmo
input loop, the undo stack and the Save/toast plumbing; this module owns the
decal working list and everything that turns it into a live renderer
override (`host_io.set_instance_decals`) and a `decals.json` write
(`decals_writer.save_decals`).

Frames. Every `Placement` is in the SHIP-BODY frame, in UNSCALED model units
-- the frame `decals.json` and the shader's `p_body` use. The SPV works in
the player's SET coordinates (its orbit camera, its gizmo origins), and
`ray_trace_mesh` answers in VIEW coordinates. So a hull click goes
cursor -> `manual_aim.cursor_ray` (set coords, the exact inverse of the SPV
projection) -> shifted into view coords -> `ray_trace_mesh` -> the hit
shifted back -> `world_hit_to_body` (R^T (p - loc) / scale, normal R^T n).
The gizmo goes the other way through `body_to_world` (loc + R (scale p)),
so a drag of `t` GU along a world gizmo axis is `t / scale` model units.
"""
from __future__ import annotations

import json
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
# The shader has four decal units (8..11); decals.json may declare no more.
MAX_DECALS = 4
# Offered by the Add picker alongside the registry's own unplaced PNG stems.
# Keyboard -> CEF forwarding does not exist, so the name is CHOSEN, not typed.
SUGGESTED_NAMES = ("top", "bottom", "port", "starboard", "bow", "stern")
# While the pane is open the override is re-pushed at least this often, even
# unchanged, so the native mask cache sees a PNG re-exported from Gimp
# (Ruling K: it reloads on an mtime change, checked at push time).
OVERRIDE_REFRESH_S = 1.0
MISS_HINT = "Missed the hull -- click on the ship"
CAP_HINT = "At most %d decals per ship -- delete one first" % MAX_DECALS
NUDGE_FIELDS = ("x", "y", "z", "width", "roll", "depth")
MIN_DEPTH = 1e-4


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


def _rotation_cols(ship):
    """The three columns of the ship's world rotation (identity if absent)."""
    from engine.appc.math import TGMatrix3
    rot = ship.GetWorldRotation() if hasattr(ship, "GetWorldRotation") else None
    if not isinstance(rot, TGMatrix3):
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    cols = []
    for i in range(3):
        c = rot.GetCol(i)
        cols.append((c.x, c.y, c.z))
    return tuple(cols)


def _ship_scale(ship) -> float:
    s = float(ship.GetScale()) if hasattr(ship, "GetScale") else 1.0
    return s if s > 1e-9 else 1.0


def world_hit_to_body(ship, point: Vec3, normal: Vec3) -> Tuple[Vec3, Vec3]:
    """A world (set-coordinate) hull hit -> (body point, body unit normal).
    Body point = R^T (point - loc) / scale; normal = R^T normal (rotation
    only, renormalised). Inverse of `body_to_world` / `body_dir_to_world`."""
    loc = ship.GetWorldLocation()
    d = (point[0] - loc.x, point[1] - loc.y, point[2] - loc.z)
    cols = _rotation_cols(ship)
    s = _ship_scale(ship)
    pb = tuple((d[0] * c[0] + d[1] * c[1] + d[2] * c[2]) / s for c in cols)
    nb = tuple(normal[0] * c[0] + normal[1] * c[1] + normal[2] * c[2] for c in cols)
    m = math.sqrt(sum(v * v for v in nb)) or 1.0
    return pb, tuple(v / m for v in nb)


def body_dir_to_world(ship, v: Vec3) -> Vec3:
    cols = _rotation_cols(ship)
    return tuple(cols[0][k] * v[0] + cols[1][k] * v[1] + cols[2][k] * v[2]
                 for k in range(3))


def body_to_world(ship, p: Vec3) -> Vec3:
    s = _ship_scale(ship)
    w = body_dir_to_world(ship, (p[0] * s, p[1] * s, p[2] * s))
    loc = ship.GetWorldLocation()
    return (loc.x + w[0], loc.y + w[1], loc.z + w[2])


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
        self._decal_registries: List[str] = []
        self._decal_registry: Optional[str] = None
        self._decal_selected: Optional[str] = None
        self._decal_adding: Optional[str] = None   # name awaiting a hull click
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

    def _decal_index(self, name) -> Optional[int]:
        for i, p in enumerate(self._decal_working or []):
            if p.name == name:
                return i
        return None

    def _decal_scan_registries(self) -> List[str]:
        """Registry folders under the class's Masks/, across the replacements
        overlay, installed mods and the stock tree (case-folded, sorted)."""
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
                if c.is_dir():
                    names.setdefault(c.name.lower(), c.name)
        return sorted(names.values(), key=str.lower)

    def _decal_mask_path(self, name: str) -> Optional[Path]:
        """The previewed registry's PNG for placement `name`, or None."""
        from engine import paths
        d, reg = self._decal_dir(), self._decal_registry
        if d is None or not reg:
            return None
        p = paths.game_asset(f"{d}/Masks/{reg}/{name}.png")
        return p if p.is_file() else None

    def _decal_aspect(self, name: str) -> float:
        m = self._decal_mask_path(name)
        a = png_aspect(m) if m is not None else None
        return a if a is not None else DEFAULT_MASK_ASPECT

    def _decal_ship_radius(self, ship) -> float:
        """The ship's radius in MODEL units (the placement frame)."""
        r = float(ship.GetRadius()) if hasattr(ship, "GetRadius") else 0.0
        r /= _ship_scale(ship)
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
        working, default, doc = [], None, None
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
                    self._decal_error = ("Skipped malformed placement %r" % name)
        self._decal_working = working
        self._decal_baseline = list(working)
        self._decal_default = default
        self._decal_baseline_default = default
        reg = hull_decals.resolve_registry(
            registry_texture.replacements_for(ship) if ship is not None else [],
            doc if isinstance(doc, dict) else None)
        if reg is None and self._decal_registries:
            reg = self._decal_registries[0]
        self._decal_registry = reg

    def _decal_dirty(self) -> bool:
        return (self._decal_working is not None
                and (self._decal_working != self._decal_baseline
                     or self._decal_default != self._decal_baseline_default))

    def _decal_change_count(self) -> int:
        if not self._decal_dirty():
            return 0
        base = {p.name: p for p in self._decal_baseline}
        work = {p.name: p for p in self._decal_working}
        n = sum(1 for k in set(base) | set(work) if base.get(k) != work.get(k))
        if self._decal_default != self._decal_baseline_default:
            n += 1
        return max(n, 1)

    # ------------------------------------------------------------------
    # The live override
    # ------------------------------------------------------------------
    def _decal_entries(self) -> list:
        out = []
        for p in (self._decal_working or [])[:MAX_DECALS]:
            mask = self._decal_mask_path(p.name) or placeholder_path()
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
            self._decal_reposition = False
            if len(self._decal_working) >= MAX_DECALS:
                self._decal_adding, self._decal_error = None, CAP_HINT
                return True
            err = decal_editor.valid_name(arg, self._decal_names())
            if err is not None:
                self._decal_adding, self._decal_error = None, "Name refused: " + err
                return True
            self._decal_adding, self._decal_error = arg, None
            return True
        if verb == "decal-add-cancel":
            self._decal_adding = None
            self._decal_error = None
            return True
        if verb == "decal-delete":
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
            if arg and decal_editor.valid_name(arg, ()) is not None:
                return False
            self._decal_default = arg or None
            return True
        if verb == "decal-reposition":
            if self._decal_selected is None:
                return False
            self._decal_reposition = not self._decal_reposition
            self._decal_adding = None
            return True
        if verb == "decal-nudge":
            return self._decal_nudge(arg)
        return False

    def _decal_nudge(self, arg: str) -> bool:
        i = self._decal_index(self._decal_selected)
        if i is None:
            return False
        try:
            a = json.loads(arg)
            field, delta = str(a["field"]), float(a["delta"])
        except (ValueError, KeyError, TypeError):
            return False
        if field not in NUDGE_FIELDS or not math.isfinite(delta):
            return False
        p = self._decal_working[i]
        if field in ("x", "y", "z"):
            k = "xyz".index(field)
            o = list(p.origin)
            o[k] += delta
            p = replace(p, origin=tuple(o))
        elif field == "width":
            w = decal_editor.width(p) + delta
            if w <= 0.0:
                return False
            p = decal_editor.set_width(p, w, self._decal_aspect(p.name))
        elif field == "roll":
            p = decal_editor.roll(p, math.radians(delta))
        else:
            p = replace(p, depth=max(MIN_DEPTH, p.depth + delta))
        self._decal_working[i] = p
        return True

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
        hp = frames.shifted(TGPoint3(px, py, pz), off, -1.0)
        return world_hit_to_body(ship, (hp.x, hp.y, hp.z), tuple(normal))

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
                p = decal_editor.place_at_hit(
                    name, pb, nb, BODY_FORWARD, BODY_UP,
                    self._decal_ship_radius(self._ship_getter()),
                    self._decal_aspect(name))
                self._decal_working.append(p)
                self._decal_selected = name
                self._decal_adding = None
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

    def _decal_gizmo(self) -> Optional[dict]:
        kind = {"transform": 0, "scale": 1, "rotate": 2}.get(self.active_tool)
        p = self._decal_target()
        ship = self._ship_getter()
        if kind is None or p is None or ship is None or self.camera is None:
            return None
        from engine.ui.ship_property_viewer import gizmo_length
        axes = tuple(body_dir_to_world(ship, _unit(v))
                     for v in (p.u_axis, p.v_axis, p.normal))
        return {"origin": body_to_world(ship, decal_editor.centre(p)),
                "axes": axes, "length": gizmo_length(self.camera),
                "highlight": self._gizmo_hover, "handle_kind": kind}

    def _decal_grab_allowed(self, handle: int) -> bool:
        """Move has no normal arrow and Rotate only the ring about the
        normal: those handles are drawn (the gizmo pass draws three) but
        never grabbed."""
        if self.active_tool == "transform":
            return handle in (0, 1)
        if self.active_tool == "rotate":
            return handle == 2
        return True

    def _decal_begin_drag(self, handle: int, grab_param: float) -> bool:
        p = self._decal_target()
        if p is None:
            return False
        self._drag_undo_before = self._snapshot_pending()
        self._decal_grab = p
        self._axis_drag = handle
        self._axis_grab_param = grab_param
        return True

    def _decal_apply(self, new_p) -> None:
        i = self._decal_index(self._decal_selected)
        if i is None:
            return
        self._decal_working[i] = new_p
        self._last_pushed = None
        self._decal_sync_override()

    def _decal_apply_axis_drag(self, param_now: float) -> None:
        d = (param_now - self._axis_grab_param) / _ship_scale(self._ship_getter())
        if self._axis_drag == 0:
            self._decal_apply(decal_editor.move_uv(self._decal_grab, d, 0.0))
        elif self._axis_drag == 1:
            self._decal_apply(decal_editor.move_uv(self._decal_grab, 0.0, d))

    def _decal_apply_scale_drag(self, t_now: float) -> None:
        from engine.ui.ship_property_viewer import gizmo_length
        L = gizmo_length(self.camera)
        ratio = max(t_now / max(self._axis_grab_param, 0.25 * L), 1e-3)
        self._decal_apply(decal_editor.scale(self._decal_grab, ratio))

    def _decal_apply_ring_drag(self, d_body: float) -> None:
        self._decal_apply(decal_editor.roll(self._decal_grab, d_body))

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def _decal_state_key(self) -> tuple:
        return (self._decals_active,
                tuple(self._decal_working) if self._decal_working is not None else None,
                self._decal_registry, self._decal_default,
                tuple(self._decal_registries), self._decal_selected,
                self._decal_adding, self._decal_reposition, self._decal_error)

    def _decal_suggested_names(self) -> List[str]:
        """Names the Add picker offers: the previewed registry's PNG stems
        not yet placed, then the stock suggestions; all valid and unused."""
        from engine import paths
        taken = self._decal_names()
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
        out += list(SUGGESTED_NAMES)
        seen, result = set(), []
        for n in out:
            if n.lower() in seen:
                continue
            seen.add(n.lower())
            if decal_editor.valid_name(n, taken) is None:
                result.append(n)
        return result

    def _decal_numbers(self) -> Optional[dict]:
        p = self._decal_target()
        if p is None:
            return None
        w = decal_editor.width(p)
        try:
            roll_deg = math.degrees(decal_editor.roll_angle(p, BODY_FORWARD, BODY_UP))
        except ValueError:
            roll_deg = 0.0
        return {"centre": list(decal_editor.centre(p)), "width": w,
                "roll": roll_deg, "depth": p.depth,
                "step": max(w * 0.05, 1e-3)}

    def _decals_payload(self) -> dict:
        working = self._decal_working or []
        return {
            "active": self._decals_active,
            "has_model": self._decal_model_rel is not None,
            "registries": list(self._decal_registries),
            "registry": self._decal_registry,
            "default_registry": self._decal_default,
            "placements": [{"name": p.name,
                            "has_mask": self._decal_mask_path(p.name) is not None}
                           for p in working],
            "selected": self._decal_selected,
            "adding": self._decal_adding is not None,
            "adding_name": self._decal_adding,
            "reposition": self._decal_reposition,
            "error": self._decal_error,
            "can_add": len(working) < MAX_DECALS,
            "suggested_names": (self._decal_suggested_names()
                                if self._decals_active else []),
            "numbers": self._decal_numbers(),
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
                self._decal_model_rel, list(self._decal_working), self._decal_default)
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv decal save", e)
            self._show_toast("Decal save failed: %s" % e)
            return False
        self._decal_baseline = list(self._decal_working)
        self._decal_baseline_default = self._decal_default
        self._show_toast("Saved decals to %s" % path)
        return True
