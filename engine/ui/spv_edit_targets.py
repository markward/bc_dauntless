"""Per-kind edit targets for the Ship Property Viewer's editing tools.

Spec: docs/superpowers/specs/2026-09-29-spv-edit-target-refactor-design.md
(section 3). Every SPV tool -- Move, Rotate, Scale, their Copy/Paste,
Mirror, Pipette and the gizmo drags -- is to be written once against an
`EditTarget`: a thin view over `ShipPropertyViewerPanel`'s staged-edit
state for ONE selected thing (a subsystem mount, a light volume, an
emitter, a part anchor or pose, or a decal). An adapter owns no state, so
staging, undo snapshots and Save are unchanged.

A capability a kind lacks is `None` / empty / a no-op here. Task 2 routes
the Move tool (position, coord clipboard kind, gizmo frame, axis drag, mount
lock) through the adapters; Task 3 the Scale tool (size fields, scale
clipboard kind, gizmo, handle drag); Task 4 the Rotate tool (rotate kind and
readout, stepper nudge, copy/paste value, ring drag, rotate gizmo, and the
rotation half of Mirror); Task 5 the Pipette (`pipette_fields_from`, an
emitter's `colour`) and Mirror Element (`mirror()` = `mirror_position()` +
`mirror_rotation()`); Task 6 decals (`DecalTarget`, which gains Copy/Paste
and a Mirror that creates a new placement).
"""
import math



class EditTarget:
    """Thin per-kind view over ShipPropertyViewerPanel's staged state
    (spec 2026-09-29-spv-edit-target-refactor §3). Owns no state."""
    kind: str = ""                      # "subsystem"|"light"|"emitter"|"part_anchor"|"part_pose"|"decal"
    def __init__(self, panel, key: tuple): self.panel, self.key = panel, key
    @property
    def locked(self) -> bool: return False
    # Move
    def position(self) -> tuple: raise NotImplementedError
    def set_position(self, xyz: tuple) -> None: raise NotImplementedError
    def gizmo_frame(self): return None           # (origin_world, axes) or None
    def axis_drag_apply(self, param_now: float) -> None:
        """Move the target to the grab-time coordinate with the grabbed axis
        component advanced by (param_now - grab_param)."""
        p = self.panel
        k = p._axis_drag
        base = list(p._axis_grab_pos)
        base[k] += (param_now - p._axis_grab_param)
        # Anchor -> the anchor; pose -> its translation (and the preview);
        # emitter / light / subsystem -> its staged position.
        self.set_position(tuple(base))
    def payload_extras(self, tool: str) -> dict:
        """Kind-specific keys added to the "coord"/"rotate"/"scale" panel
        payload (a decal's `decal`, `step_scale`, `can_mirror`)."""
        return {}
    # Rotate
    def rotate_spec(self):                       # dict {fields, clipboard_kind} | None
        """The Rotate panel's X/Y/Z readout and clipboard kind, or None when
        this target has no rotation (`rotate_kind()` is None)."""
        kind = self.rotate_kind()
        if kind is None:
            return None
        acc = self._rotate_readout()
        return {"fields": [{"label": "X", "value": acc[0]},
                           {"label": "Y", "value": acc[1]},
                           {"label": "Z", "value": acc[2]}],
                "clipboard_kind": kind}
    def _rotate_readout(self):
        # Keyed by the full target tuple (("light", i) / ("emitter", i, j)) so a
        # subsystem's light readout stays independent of that same subsystem's
        # emitter readouts — a bare index i would collide.
        return self.panel._rotate_accum.get(self.key, [0.0, 0.0, 0.0])
    def get_rotation(self): return None          # the rotate-clipboard value
    def set_rotation(self, value) -> None: pass  # absolute (Paste)
    def rotate_nudge(self, index: int, delta: float) -> None: pass
    def ring_drag_begin(self, *args): return None
    def ring_drag_apply(self, state, angle: float) -> None: pass
    def rotate_gizmo_frame(self): return None    # (origin_world, axes) or None
    # Scale
    def scale_spec(self): return None            # dict {kind, fields, step_scale} | None
    def get_scale(self): return None
    def set_scale_field(self, name: str, value: float) -> None: pass
    def scale_drag_begin(self, *args): return None
    def scale_drag_apply(self, state, *args) -> None: pass
    def scale_gizmo_frame(self): return None     # (origin_world, axes) or None
    # Clipboards
    def coord_kind(self) -> str: return ""
    def rotate_kind(self): return None
    def scale_kind(self): return None
    # Mirror / pipette
    def mirror_position(self) -> None:
        """Reflect the coordinate across the ship X axis (x -> -x): the
        coord Mirror. On a part pose that is the POSED anchor (ruling 15)."""
        pos = self.position()
        if pos is not None:
            p = list(pos); p[0] = -p[0]
            self.set_position(tuple(p))
    def mirror_rotation(self) -> None: pass      # the Rotate tool's Mirror
    def mirror(self) -> None:
        """Mirror Element: the position x-flip, then this kind's rotation
        mirror (a part pose's rotation holds the just-mirrored anchor)."""
        self.mirror_position()
        self.mirror_rotation()
    def pipette_fields_from(self, src: "EditTarget") -> tuple: return ()
    def pipette_arms(self) -> bool:
        """Whether the Pipette arms with this target selected."""
        return True

def _ship_with_rotation(panel):
    """The panel's ship if it can be resolved with a world rotation, else
    None -- the guard every gizmo applies before placing itself."""
    ship = panel._ship_getter()
    if ship is None or not hasattr(ship, "GetWorldRotation"):
        return None
    return ship


def _set_grab_origin_from_body(panel, pos) -> None:
    """Drag-start world origin at body `pos`, set only when the ship
    resolves (otherwise `_axis_grab_origin` is left as it was)."""
    ship = panel._ship_getter()
    if ship is not None and hasattr(ship, "GetWorldRotation"):
        from engine.ui.ship_property_viewer import world_from_body
        panel._axis_grab_origin = world_from_body(ship, pos)


class _HardpointMount(EditTarget):
    """Shared by the three hardpoint mount kinds (subsystem, light,
    emitter): the "mount" coord-clipboard tag -- they interchange freely, as
    they always have -- and the mount-editing lock."""

    def coord_kind(self) -> str:
        return "mount"

    @property
    def locked(self) -> bool:
        """True when mount editing is locked (was the panel's
        `_current_target_is_locked_mount` for a subsystem/light/emitter
        target) -- refuses gizmo grabs, drags and nudges."""
        return not self.panel._mount_editing_enabled()

    # -- Pipette -------------------------------------------------------
    def pipette_fields_from(self, src) -> tuple:
        """Every aspect this target can take from pipette source `src`, in
        the order the Pipette applies them. Position always (when the source
        has one); rotation only when both share a rotate kind; scale only
        when both share a scale kind; colour + intensity emitter -> emitter
        only. Incompatible aspects are silently skipped."""
        fields = []
        if src.position() is not None:
            fields.append("position")
        rkind = self.rotate_kind()
        if rkind is not None and src.rotate_kind() == rkind:
            fields.append("rotation")
        if src.scale_kind()[0] == self.scale_kind()[0]:
            fields.append("scale")
        if src.kind == "emitter" and self.kind == "emitter":
            fields.append("colour")
        return tuple(fields)

    # -- Scale ---------------------------------------------------------
    def scale_spec(self):
        kind, fields = self.scale_kind()
        return {"kind": kind, "fields": fields}

    def get_scale(self):
        return tuple(f["value"] for f in self.scale_kind()[1])

    def set_scale_field(self, index, value) -> None:
        """Stage `value` (floored at SCALE_MIN) for size field `index`,
        routing to this kind's radius or spec staging path."""
        from engine.ui.ship_property_viewer_panel import SCALE_MIN
        value = max(SCALE_MIN, float(value))
        kind, fields = self.scale_kind()
        if not (0 <= index < len(fields)):
            return
        self._stage_scale_field(index, value)

    def _stage_scale_field(self, index, value) -> None:
        raise NotImplementedError

    def _size_spec(self) -> dict:
        """The spec whose `axis`/`up` orient this target's size handles."""
        return {}

    def scale_drag_begin(self, axis: int):
        """The (field index, grabbed value) a scale drag on gizmo handle
        `axis` edits. For xyz (Box) targets the axis picks the field; every
        other shape is uniform and scales field 0 (the radius)."""
        kind, fields = self.scale_kind()
        if kind == "xyz":
            return (axis, fields[axis]["value"])   # per-axis
        elif kind == "radius_xy_length":
            # Oriented cone: the handle aligned with `forward` (=axis) scales
            # Length (field 2); of the two perpendicular handles, the one aligned
            # with right = cross(forward, up) scales Radius X (field 0), the other
            # (aligned with up) scales Radius Y (field 1). Gizmo handles are body
            # X/Y/Z, so match each frame vector by its dominant body component.
            from engine.appc.light_emitters import _derive_up
            spec = self._size_spec()
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            right = (fwd[1]*up[2] - fwd[2]*up[1],
                     fwd[2]*up[0] - fwd[0]*up[2],
                     fwd[0]*up[1] - fwd[1]*up[0])
            def _dom(v):
                return max(range(3), key=lambda k: abs(v[k]))
            if axis == _dom(fwd):
                field_idx = 2
            elif axis == _dom(right):
                field_idx = 0
            else:
                field_idx = 1
            return (field_idx, fields[field_idx]["value"])
        elif kind == "radius_length":
            # Cylinder light OR strip emitter: the handle aligned with the
            # node's body-frame axis scales Length (field 1); the two
            # perpendicular handles scale Radius (field 0). The gizmo axes are
            # body X/Y/Z, so the aligned handle is the dominant component of the
            # region's/emitter's body-frame axis vector.
            av = self._size_spec().get("axis", (0.0, -1.0, 0.0))
            aligned = max(range(3), key=lambda k: abs(av[k]))
            field_idx = 1 if axis == aligned else 0
            return (field_idx, fields[field_idx]["value"])
        else:
            return (0, fields[0]["value"])          # uniform -> radius

    def scale_drag_apply(self, state, ratio: float) -> None:
        """Scale the grabbed field (`state`, as `scale_drag_begin`
        returned it) by `ratio`."""
        idx, grab_val = state
        self.set_scale_field(idx, grab_val * ratio)

    def scale_gizmo_frame(self):
        """The scale gizmo's (origin, axes): the Move gizmo's frame, after
        the scale gizmo's own guard -- a stale/removed node or out-of-range
        index must degrade to None, never crash on a missing spec (this runs
        every input frame via _active_gizmo)."""
        if not (0 <= self.key[1] < len(self.panel._descriptors)):
            return None
        return self.gizmo_frame()

    # -- Rotate --------------------------------------------------------
    def rotate_gizmo_frame(self):
        """The rotate rings' (origin, axes): at the node's position, behind
        the same stale-index guard as the scale gizmo."""
        return self.scale_gizmo_frame()

    def ring_drag_begin(self) -> None:
        """Capture a light/emitter rotate target's grab-start axis,
        orientation and degree accumulators (see the panel's
        `_begin_ring_drag`)."""
        p = self.panel
        t = self.key
        spec = self._size_spec()
        p._ring_grab_axis = tuple(spec.get("axis") or (0.0, -1.0, 0.0))
        if t[0] == "emitter" and spec.get("kind") == "cone":
            # A cone rotates from its (forward=axis, up) basis, like a Box light;
            # seed the grab-start orientation from it (deriving up if absent) so
            # the ring drag rolls the ellipse + re-aims from the grab pose.
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            p._ring_grab_orientation = (tuple(fwd), tuple(up))
        else:
            p._ring_grab_orientation = spec.get("orientation") \
                or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        # Keyed by the full target tuple so light and emitter accumulators on
        # the same subsystem stay independent (see rotate_spec).
        p._ring_grab_accum = list(p._rotate_accum.get(t, [0.0, 0.0, 0.0]))


class MountTarget(_HardpointMount):
    """A subsystem mount (sphere): key ("subsystem", i)."""
    kind = "subsystem"

    def position(self):
        p = self.panel
        _, i = self.key
        return tuple(float(c) for c in p._effective_pos(i))

    def set_position(self, xyz) -> None:
        self.panel.set_subsystem_position(self.key[1], xyz)

    def gizmo_frame(self):
        p = self.panel
        if not (0 <= self.key[1] < len(p._descriptors)):
            return None
        ship = _ship_with_rotation(p)
        if ship is None:
            return None
        from engine.ui.ship_property_viewer import gizmo_axes
        origin = p._effective_world_pos(self.key[1])
        return origin, gizmo_axes(ship.GetWorldRotation())

    def axis_drag_begin(self, axis: int, grab_param: float) -> None:
        p = self.panel
        _, i = self.key
        p._axis_drag = axis
        p._axis_grab_param = grab_param
        p._axis_grab_pos = p._effective_pos(i)
        p._axis_grab_origin = p._effective_world_pos(i)

    def scale_kind(self):
        # A subsystem is always a sphere (`radius`).
        p = self.panel
        i = self.key[1]
        r = p._effective_radius(i, p._descriptors[i].get("properties", {}).get("radius"))
        try:
            r = float(r)
        except (TypeError, ValueError):
            r = 0.0
        return "radius", [{"label": "Radius", "value": r}]

    def _stage_scale_field(self, index, value) -> None:
        self.panel._pending_radius[self.key[1]] = value
        self.panel._last_pushed = None


class LightTarget(_HardpointMount):
    """A light volume (Sphere, Cylinder or Box): key ("light", i)."""
    kind = "light"

    def position(self):
        spec = self.panel._effective_light(self.key[1])
        return tuple(float(c) for c in spec["position"]) if spec else None

    def set_position(self, xyz) -> None:
        self.panel.set_light_position(self.key[1], xyz)

    def gizmo_frame(self):
        p = self.panel
        ship = _ship_with_rotation(p)
        if ship is None:
            return None
        from engine.ui.ship_property_viewer import gizmo_axes, world_from_body
        light = p._effective_light(self.key[1])
        if light is None:
            return None
        origin = world_from_body(ship, light["position"])
        return origin, gizmo_axes(ship.GetWorldRotation())

    def axis_drag_begin(self, axis: int, grab_param: float) -> None:
        p = self.panel
        _, i = self.key
        p._axis_drag = axis
        p._axis_grab_param = grab_param
        p._axis_grab_pos = tuple(p._effective_light(i)["position"])
        _set_grab_origin_from_body(p, p._axis_grab_pos)

    def scale_kind(self):
        # Fields depend on the shape: `Box` -> xyz axes, `Cylinder` ->
        # radius+length, else -> radius.
        spec = self.panel._effective_light(self.key[1])
        if not spec:
            return "radius", [{"label": "Radius", "value": 0.0}]
        shape = spec.get("shape", "Sphere")
        if shape == "Box":
            sx, sy, sz = spec.get("scale", (0.25, 0.25, 0.25))
            return "xyz", [{"label": "X", "value": float(sx)},
                           {"label": "Y", "value": float(sy)},
                           {"label": "Z", "value": float(sz)}]
        if shape == "Cylinder":
            r = spec.get("radius", (0.25,))[0]
            aft, fore = spec.get("extent", (0.0, 2.0))
            return "radius_length", [{"label": "Radius", "value": float(r)},
                                     {"label": "Length", "value": float(fore) - float(aft)}]
        return "radius", [{"label": "Radius", "value": float(spec.get("radius", (0.25,))[0])}]

    def _size_spec(self) -> dict:
        return self.panel._effective_light(self.key[1]) or {}

    def _stage_scale_field(self, index, value) -> None:
        p = self.panel
        i = self.key[1]
        spec = dict(p._effective_light(i) or {})
        if not spec:
            return
        shape = spec.get("shape", "Sphere")
        if shape == "Box":
            sc = list(spec.get("scale", (0.25, 0.25, 0.25)))
            sc[index] = value
            spec["scale"] = tuple(sc)
        elif shape == "Cylinder":
            if index == 0:
                spec["radius"] = (value,)
            else:
                # Length scales the extent about the anchor (pos = offset 0,
                # where the gizmo sits), NOT by holding the aft end fixed —
                # so a pos-centred cylinder grows symmetrically instead of
                # sliding off one end. Proportional scale keeps offset 0 fixed.
                aft, fore = spec.get("extent", (0.0, 2.0))
                length = fore - aft
                if abs(length) > 1e-9:
                    r = value / length
                    spec["extent"] = (aft * r, fore * r)
                else:
                    spec["extent"] = (-value / 2.0, value / 2.0)
        else:
            spec["radius"] = (value,)
        p._pending_light[i] = spec
        p._last_pushed = None


    # -- Rotate --------------------------------------------------------
    def rotate_kind(self):
        # A Cylinder rotates its `axis`, a Box its forward+up `orientation`
        # basis; a Sphere (or a missing spec) has no rotation. Tags:
        # `box_orientation` for a Box, `cylinder_axis` for a Cylinder --
        # shared INTENTIONALLY with a strip emitter (both rotate a single
        # axis, so a rotation copies/pastes/mirrors between them).
        spec = self.panel._effective_light(self.key[1])
        if not spec or spec.get("shape") not in ("Cylinder", "Box"):
            return None
        return "box_orientation" if spec.get("shape") == "Box" \
            else "cylinder_axis"

    def get_rotation(self):
        spec = self.panel._effective_light(self.key[1]) or {}
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") \
                or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            return (tuple(fwd), tuple(up))
        axis = spec.get("axis") or (0.0, -1.0, 0.0)
        return tuple(axis)

    def set_rotation(self, value) -> None:
        if self.rotate_kind() == "box_orientation":
            # box_orientation only matches a Box LIGHT target (an emitter
            # kind is cylinder_axis/cone_orientation).
            fwd, up = value
            self.panel._set_orientation_absolute(self.key[1], fwd, up)
        else:
            self.panel._set_axis_absolute(self.key, value)

    def rotate_nudge(self, index, delta_deg) -> None:
        """Rotate by `delta_deg` about basis axis `index` (Rodrigues, via
        rotate_about_axis) and bump that axis's degree accumulator. A
        Cylinder rotates its `axis`; a Box rotates BOTH `forward` and `up`
        of its orientation basis, then re-orthonormalizes."""
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        p = self.panel
        t = self.key
        ang = math.radians(delta_deg)
        _, i = t
        spec = dict(p._effective_light(i) or {})
        if not spec:
            return
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            fwd = rotate_about_axis(fwd, index, ang)
            up = rotate_about_axis(up, index, ang)
            spec["orientation"] = orthonormalize_basis(fwd, up)
        else:
            axis = spec.get("axis") or (0.0, -1.0, 0.0)
            spec["axis"] = rotate_about_axis(axis, index, ang)
        p._pending_light[i] = spec
        p._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])[index] += delta_deg
        p._last_pushed = None

    def ring_drag_apply(self, k, d_body) -> None:
        """Rotate the grab-start axis (Cylinder) or BOTH forward and up of
        the grab-start orientation (Box, then re-orthonormalized) by body
        angle `d_body` (radians) about ring axis `k`."""
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        p = self.panel
        t = self.key
        _, i = t
        spec = dict(p._effective_light(i) or {})
        if not spec:
            return
        if spec.get("shape") == "Box":
            fwd, up = p._ring_grab_orientation
            fwd = rotate_about_axis(fwd, k, d_body)
            up = rotate_about_axis(up, k, d_body)
            spec["orientation"] = orthonormalize_basis(fwd, up)
        else:
            spec["axis"] = rotate_about_axis(p._ring_grab_axis, k, d_body)
        p._pending_light[i] = spec
        p._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])
        p._rotate_accum[t][k] = p._ring_grab_accum[k] + math.degrees(d_body)
        p._last_pushed = None

    def mirror_rotation(self) -> None:
        """Reflect the orientation across the ship X axis (starboard):
        negate X of the axis (Cylinder) or of both forward and up (Box),
        then set it absolutely. Rotation only (`mirror()` adds the position
        flip); a Sphere has no rotation and is untouched."""
        if self.rotate_kind() is None:
            return
        p = self.panel
        t = self.key
        _, i = t
        spec = p._effective_light(i) or {}
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            p._set_orientation_absolute(i, (-fwd[0], fwd[1], fwd[2]),
                                        (-up[0], up[1], up[2]))
        else:
            axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
            axis[0] = -axis[0]
            p._set_axis_absolute(t, axis)


class EmitterTarget(_HardpointMount):
    """A subsystem emitter (point, strip or cone): key ("emitter", i, j)."""
    kind = "emitter"

    def position(self):
        _, i, j = self.key
        spec = self.panel._effective_emitter(i, j)
        return tuple(float(c) for c in spec["position"]) if spec else None

    def set_position(self, xyz) -> None:
        _, i, j = self.key
        self.panel.set_emitter_position(i, j, xyz)

    def gizmo_frame(self):
        p = self.panel
        ship = _ship_with_rotation(p)
        if ship is None:
            return None
        from engine.ui.ship_property_viewer import gizmo_axes, world_from_body
        spec = p._effective_emitter(self.key[1], self.key[2])
        if spec is None:
            return None
        origin = world_from_body(ship, spec["position"])
        return origin, gizmo_axes(ship.GetWorldRotation())

    def axis_drag_begin(self, axis: int, grab_param: float) -> None:
        p = self.panel
        _, i, j = self.key
        spec = p._effective_emitter(i, j)
        if spec is None:
            return
        p._axis_drag = axis
        p._axis_grab_param = grab_param
        p._axis_grab_pos = tuple(float(c) for c in spec["position"])
        _set_grab_origin_from_body(p, p._axis_grab_pos)

    def scale_kind(self):
        # Scalar `radius`/`length`: a point emitter exposes only Radius; a
        # strip or cone exposes Radius + Length (the cone's half-angle is
        # DERIVED from radius/length, so no separate field).
        _, i, j = self.key
        spec = self.panel._effective_emitter(i, j)
        if not spec:
            return "radius", [{"label": "Radius", "value": 0.0}]
        kind = spec.get("kind", "point")
        if kind == "point":
            return "radius", [{"label": "Radius", "value": float(spec["radius"])}]
        if kind == "cone":
            # A cone now has TWO base radii (X = radius, Y = radius_y) plus a
            # Length, so it exposes a 3-field kind (mirrors the Box light's
            # xyz). A circular/legacy cone reports Radius Y == Radius X.
            return "radius_xy_length", [
                {"label": "Radius X", "value": float(spec["radius"])},
                {"label": "Radius Y",
                 "value": float(spec.get("radius_y", spec["radius"]))},
                {"label": "Length", "value": float(spec["length"])}]
        # strip exposes Radius + Length.
        return "radius_length", [
            {"label": "Radius", "value": float(spec["radius"])},
            {"label": "Length", "value": float(spec["length"])}]

    def _size_spec(self) -> dict:
        return self.panel._effective_emitter(self.key[1], self.key[2]) or {}

    # -- Colour (Pipette, emitter -> emitter) --------------------------
    def colour(self):
        """(color, intensity), or None when the emitter is gone."""
        ssp = self.panel._effective_emitter(self.key[1], self.key[2])
        if ssp is None:
            return None
        return (tuple(ssp["color"]), float(ssp["intensity"]))

    def set_colour(self, value) -> None:
        """Stage `value` = (color, intensity), restaging the whole compacted
        list. None (a vanished source) is a no-op."""
        if value is None:
            return
        p = self.panel
        _, ti, tj = self.key
        lst = list(p._effective_emitters(ti))
        if 0 <= tj < len(lst):
            spec = dict(lst[tj])
            spec["color"] = tuple(value[0])
            spec["intensity"] = float(value[1])
            lst[tj] = spec
            p._pending_emitter[ti] = lst
            p._last_pushed = None

    def _stage_scale_field(self, index, value) -> None:
        # Emitter spec uses SCALAR radius/length floats (NOT the light's
        # tuple/extent form). Field 0 -> radius, field 1 -> length; restage
        # the whole compacted list to keep indices dense.
        p = self.panel
        _, i, j = self.key
        lst = list(p._effective_emitters(i))
        if not (0 <= j < len(lst)):
            return
        spec = dict(lst[j])
        if spec.get("kind") == "cone":
            # 3 fields: 0 -> Radius X (radius), 1 -> Radius Y (radius_y),
            # 2 -> Length. index is bounds-checked against the 3-field kind.
            spec[("radius", "radius_y", "length")[index]] = value
        else:  # strip / point: field 0 -> radius, field 1 -> length
            spec["radius" if index == 0 else "length"] = value
        lst[j] = spec
        p._pending_emitter[i] = lst
        p._last_pushed = None


    # -- Rotate --------------------------------------------------------
    def rotate_kind(self):
        # A strip rotates its single `axis` (`cylinder_axis`, shared
        # INTENTIONALLY with a Cylinder light); a cone carries a full
        # forward+up basis (`cone_orientation`, only interchanging with other
        # cones); a point emitter (or a missing spec) has no rotation.
        spec = self.panel._effective_emitter(self.key[1], self.key[2])
        if not spec or spec.get("kind") not in ("strip", "cone"):
            return None
        return "cone_orientation" if spec.get("kind") == "cone" \
            else "cylinder_axis"

    def get_rotation(self):
        _, i, j = self.key
        spec = self.panel._effective_emitter(i, j) or {}
        if spec.get("kind") == "cone":
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            return (tuple(fwd), tuple(up))
        axis = spec.get("axis") or (0.0, -1.0, 0.0)
        return tuple(axis)

    def set_rotation(self, value) -> None:
        if self.rotate_kind() == "cone_orientation":
            # cone_orientation only matches a CONE emitter target.
            fwd, up = value
            self.panel._set_orientation_absolute(self.key, fwd, up)
        else:
            self.panel._set_axis_absolute(self.key, value)

    def rotate_nudge(self, index, delta_deg) -> None:
        """Rotate by `delta_deg` about basis axis `index` and bump that
        axis's degree accumulator."""
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        p = self.panel
        t = self.key
        ang = math.radians(delta_deg)
        # A CONE carries an oriented (forward=axis, up) basis like a Box, so
        # it rotates BOTH and re-orthonormalizes; a strip rotates its single
        # `axis` (same math as the cylinder-light branch). Restage the whole
        # compacted list to keep emitter indices dense.
        _, i, j = t
        lst = list(p._effective_emitters(i))
        if not (0 <= j < len(lst)):
            return
        spec = dict(lst[j])
        if spec.get("kind") == "cone":
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            fwd = rotate_about_axis(fwd, index, ang)
            up = rotate_about_axis(up, index, ang)
            spec["axis"], spec["up"] = orthonormalize_basis(fwd, up)
        else:
            axis = spec.get("axis") or (0.0, -1.0, 0.0)
            spec["axis"] = rotate_about_axis(axis, index, ang)
        lst[j] = spec
        p._pending_emitter[i] = lst
        p._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])[index] += delta_deg
        p._last_pushed = None

    def ring_drag_apply(self, k, d_body) -> None:
        """Rotate from the grab-start pose by body angle `d_body` (radians)
        about ring axis `k`."""
        from engine.ui.ship_property_viewer import (
            rotate_about_axis, orthonormalize_basis)
        p = self.panel
        t = self.key
        # A CONE rotates BOTH `forward` and `up` of its grab-start
        # orientation (like a Box), then re-orthonormalizes; a strip rotates
        # its single `axis`. Restage the whole compacted list.
        _, i, j = t
        lst = list(p._effective_emitters(i))
        if not (0 <= j < len(lst)):
            return
        spec = dict(lst[j])
        if spec.get("kind") == "cone":
            fwd, up = p._ring_grab_orientation
            fwd = rotate_about_axis(fwd, k, d_body)
            up = rotate_about_axis(up, k, d_body)
            spec["axis"], spec["up"] = orthonormalize_basis(fwd, up)
        else:
            spec["axis"] = rotate_about_axis(p._ring_grab_axis, k, d_body)
        lst[j] = spec
        p._pending_emitter[i] = lst
        p._rotate_accum.setdefault(t, [0.0, 0.0, 0.0])
        p._rotate_accum[t][k] = p._ring_grab_accum[k] + math.degrees(d_body)
        p._last_pushed = None

    def mirror_rotation(self) -> None:
        """Reflect the orientation across the ship X axis: negate X of the
        axis (strip) or of both forward and up (cone). Rotation only
        (`mirror()` adds the position flip); a
        point emitter has no rotation and is untouched."""
        if self.rotate_kind() is None:
            return
        p = self.panel
        t = self.key
        _, i, j = t
        spec = p._effective_emitter(i, j) or {}
        if spec.get("kind") == "cone":
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            p._set_orientation_absolute(t, (-fwd[0], fwd[1], fwd[2]),
                                        (-up[0], up[1], up[2]))
        else:
            axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
            axis[0] = -axis[0]
            p._set_axis_absolute(t, axis)


class _PartNode(EditTarget):
    """A model part's Anchor or {State} Transformation node. Never locked:
    tuning the very pose you are looking at is the point."""

    def coord_kind(self) -> str:
        # A part anchor and a posed anchor only paste onto their own kind.
        return self.key[0]

    def pipette_arms(self) -> bool:
        # A part node holds none of the aspects the pipette copies (a mount
        # position, rotation, size, colour), so it never arms.
        return False

    def gizmo_frame(self):
        p = self.panel
        ship = _ship_with_rotation(p)
        if ship is None:
            return None
        from engine.ui.ship_property_viewer import gizmo_axes, world_from_body
        # The anchor, or the POSED anchor for a state pose.
        pos = self.position()
        if pos is None:
            return None
        origin = world_from_body(ship, pos)
        return origin, gizmo_axes(ship.GetWorldRotation())

    def axis_drag_begin(self, axis: int, grab_param: float) -> None:
        # Grab the COORDINATE the drag edits (the anchor, or a pose's
        # translation) and the gizmo's world origin (the anchor, or the
        # posed anchor) -- a pose drag adds its body-frame delta to t,
        # which moves the posed anchor by exactly that delta.
        p = self.panel
        pos = self.position()
        if pos is None:
            return
        p._axis_drag = axis
        p._axis_grab_param = grab_param
        p._axis_grab_pos = self.position()
        _set_grab_origin_from_body(p, pos)

    def scale_kind(self):
        # No size at all: a kind no other target shares, so a scale
        # clipboard/pipette never matches it. scale_spec() stays None, so
        # the Scale tool is inert here.
        return "none", []


class PartAnchorTarget(_PartNode):
    """A part's Anchor node: key ("part_anchor", name). Sits at the anchor;
    setting it never touches a pose (spec 2.3, option A)."""
    kind = "part_anchor"

    def position(self):
        anchor = self.panel._effective_part(self.key[1]).get("anchor")
        return tuple(float(c) for c in anchor) if anchor is not None else None

    def set_position(self, xyz) -> None:
        self.panel._stage_part_field(
            self.key[1], anchor=tuple(float(c) for c in xyz))


class PartPoseTarget(_PartNode):
    """A part's {State} Transformation node: key ("part_pose", name, state).
    Its coordinate is the POSED anchor (fix-round ruling 15), never the raw
    translation t."""
    kind = "part_pose"

    def position(self):
        return self.panel._posed_anchor(self.key[1], self.key[2])

    def set_position(self, xyz) -> None:
        # xyz is the NEW posed anchor: translate the pose by the move,
        # t += (xyz - q_old), R unchanged (ruling 15).
        p = self.panel
        t = self.key
        p6 = p._part_pose6(t[1], t[2])
        q_old = self.position()
        if q_old is None:          # no anchor: the coordinate is t
            q_old = p6[:3]
        t_new = tuple(p6[k] + float(xyz[k]) - q_old[k] for k in range(3))
        p._stage_part_pose(t[1], t[2], t_new + p6[3:])

    # -- Rotate --------------------------------------------------------
    def rotate_kind(self):
        # A pose's three Euler angles only paste onto another pose.
        return "pose_euler"

    def _rotate_readout(self):
        # A part pose shows its OWN Euler angles (rx, ry, rz degrees, spec
        # section 3), not an accumulator: the pose IS those three numbers.
        return list(self.panel._part_pose6(self.key[1], self.key[2])[3:])

    def get_rotation(self):
        return self.panel._part_pose6(self.key[1], self.key[2])[3:]

    def set_rotation(self, value) -> None:
        # Set its three Euler angles, holding its posed anchor (ruling 14).
        self.panel._stage_pose_euler(self.key[1], self.key[2], value)

    def rotate_gizmo_frame(self):
        # Rings sit at the POSED anchor -- the pivot they rotate about.
        return self.gizmo_frame()

    def rotate_nudge(self, index, delta_deg) -> None:
        # The stepper edits that Euler component (spec section 3),
        # holding the posed anchor fixed (ruling 14).
        p = self.panel
        t = self.key
        angles = list(p._part_pose6(t[1], t[2])[3:])
        angles[index] += float(delta_deg)
        p._stage_pose_euler(t[1], t[2], angles)

    def ring_drag_begin(self) -> None:
        # A pose rotates from its GRAB-time pose about its GRAB-time
        # posed anchor, so every drag frame recomputes from the same
        # base instead of compounding (see ring_drag_apply).
        from engine.appc import part_pose
        p = self.panel
        t = self.key
        p._ring_grab_pose = part_pose.pose_from6(p._part_pose6(t[1], t[2]))
        p._ring_grab_pivot = p._posed_anchor(t[1], t[2])

    def ring_drag_apply(self, k, d_body) -> None:
        # Rotate the grab-time pose by d about body axis e_k through the
        # grab-time posed anchor q: R' = rot(e_k, d).R_grab and
        # t' = rot(e_k, d).(t_grab - q) + q. hinge_pose(q, e_k, d) is
        # exactly (rot, q - rot.q), so the new pose is that hinge
        # composed after the grab pose.
        from engine.appc import part_pose
        p = self.panel
        t = self.key
        if p._ring_grab_pivot is None:
            return
        e_k = tuple(1.0 if a == k else 0.0 for a in range(3))
        hinge = part_pose.hinge_pose(p._ring_grab_pivot, e_k,
                                     math.degrees(d_body))
        R_grab, t_grab = p._ring_grab_pose
        cols = [part_pose.apply_vector(
                    hinge, (R_grab[0][j], R_grab[1][j], R_grab[2][j]))
                for j in range(3)]
        R_new = tuple(tuple(cols[j][i] for j in range(3)) for i in range(3))
        t_new = part_pose.apply(hinge, t_grab)
        p._stage_part_pose(t[1], t[2], part_pose.pose_to6((R_new, t_new)))

    def mirror_rotation(self) -> None:
        """Flip the pose's swing in place (Mark, 2026-09-26: "Mirror just
        flips the sign"): Euler (rx, ry, rz) -> (rx, -ry, -rz), i.e. R ->
        M.R.M with M = diag(-1, 1, 1), holding the POSED ANCHOR fixed
        (`_stage_pose_euler`, ruling 14). The translation is not otherwise
        touched -- reflecting it too swung a side-mounted part about a pivot
        on the far side of the ship. The action-row Mirror adds the posed
        anchor's q.x -> -q.x (the coord Mirror); together they are the exact
        reflection M.P.M once the anchor is mirrored. Rotation only
        (`mirror()` adds the position flip first)."""
        p = self.panel
        t = self.key
        rx, ry, rz = p._part_pose6(t[1], t[2])[3:]
        p._stage_pose_euler(t[1], t[2], (rx, -ry, -rz))


class DecalTarget(EditTarget):
    """A decal placement in the active Decals pane: key ("decal", name).
    Body frame, NIF units (see spv_decals_pane's module docstring). Move is
    its centre, Rotate its roll, Scale its width (aspect-locked to its mask)
    and depth; every clipboard kind is "decal", so nothing pastes between a
    decal and any other kind. Mirror creates a NEW `<mask>_N` placement
    (spec 2026-09-29-spv-edit-target-refactor S5) instead of reflecting in
    place: an in-place half-mirror of a projector is meaningless, so the
    per-panel coord and rotate Mirrors are no-ops here (`can_mirror`)."""
    kind = "decal"

    def _placement(self):
        return self.panel._decal_by_name(self.key[1])

    def pipette_arms(self) -> bool:
        return False        # nothing a mount pipette copies applies here

    def payload_extras(self, tool: str) -> dict:
        """The decal-only keys of the Move/Rotate/Scale panel payloads:
        `decal` (stepper labelling), `step_scale` and `can_mirror`."""
        from engine.ui.spv_decals_pane import DecalsPaneMixin
        if tool == "coord":
            return {"decal": True, "can_mirror": False,
                    "step_scale": DecalsPaneMixin._decal_coord_step_scale()}
        if tool == "rotate":
            return {"decal": True, "can_mirror": False}
        return {"decal": True}

    # -- Move ----------------------------------------------------------
    def coord_kind(self) -> str:
        return "decal"

    def position(self):
        from engine.ui import decal_editor
        p = self._placement()
        return decal_editor.centre(p) if p is not None else None

    def set_position(self, xyz) -> None:
        """Re-centre the decal on `xyz`, keeping its axes, normal and depth
        (a pasted centre may float off the hull: Reposition re-seats it).
        Setting the centre it already has is a no-op."""
        from engine.ui import decal_editor
        p = self._placement()
        xyz = tuple(float(c) for c in xyz)
        if (p is None or not all(math.isfinite(c) for c in xyz)
                or xyz == tuple(decal_editor.centre(p))):
            return
        self.panel._decal_apply(decal_editor.set_centre(p, xyz))

    def gizmo_frame(self):
        """The decal's own frame: origin at its centre, axes u/v/normal (the
        Move u/v arrows, the Scale handles, the Roll ring about the normal)."""
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import (
            _unit, body_dir_to_world, body_to_world)
        p = self._placement()
        ship = self.panel._ship_getter()
        if p is None or ship is None:
            return None
        axes = tuple(body_dir_to_world(ship, _unit(v))
                     for v in (p.u_axis, p.v_axis, p.normal))
        return body_to_world(ship, decal_editor.centre(p)), axes

    def scale_gizmo_frame(self):
        return self.gizmo_frame()

    def rotate_gizmo_frame(self):
        return self.gizmo_frame()

    def axis_drag_begin(self, axis: int, grab_param: float) -> None:
        p = self._placement()
        if p is None:
            return
        pane = self.panel
        pane._decal_grab = p
        pane._axis_drag = axis
        pane._axis_grab_param = grab_param

    def axis_drag_apply(self, param_now: float) -> None:
        """Slide along u (handle 0) or v (handle 1) from the grab-time
        placement; a GU along the world axis is 1 / instance_scale units."""
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import instance_scale
        pane = self.panel
        if pane._decal_grab is None:
            return
        d = (param_now - pane._axis_grab_param) / instance_scale(pane._ship_getter())
        if pane._axis_drag == 0:
            pane._decal_apply(decal_editor.move_uv(pane._decal_grab, d, 0.0))
        elif pane._axis_drag == 1:
            pane._decal_apply(decal_editor.move_uv(pane._decal_grab, 0.0, d))

    # -- Rotate --------------------------------------------------------
    def rotate_kind(self):
        return "decal"

    def rotate_spec(self):
        """One Roll row, degrees."""
        if self._placement() is None:
            return None
        return {"fields": [{"label": "Roll",
                            "value": math.degrees(self.get_rotation())}],
                "clipboard_kind": "decal"}

    def get_rotation(self):
        """The roll (radians) against the ship's forward/up -- the 3-arg
        form, so a bow/stern decal reads its fallback reference."""
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import BODY_FORWARD, BODY_UP
        try:
            return decal_editor.roll_angle(self._placement(), BODY_FORWARD, BODY_UP)
        except ValueError:
            return 0.0

    def set_rotation(self, value) -> None:
        """Roll to `value` radians (Paste). The roll it already has is a
        no-op."""
        from engine.ui import decal_editor
        d = float(value) - self.get_rotation()
        if d == 0.0 or not math.isfinite(d):
            return
        self.panel._decal_apply(decal_editor.roll(self._placement(), d))

    def rotate_nudge(self, index, delta_deg) -> None:
        from engine.ui import decal_editor
        if index != 0 or not math.isfinite(delta_deg):
            return
        self.panel._decal_apply(
            decal_editor.roll(self._placement(), math.radians(delta_deg)))

    def ring_drag_begin(self) -> None:
        # A decal rolls from its grab-time placement.
        p = self._placement()
        if p is None:
            return
        self.panel._decal_grab = p
        self.panel._axis_grab_param = 0.0

    def ring_drag_apply(self, k, d_body) -> None:
        from engine.ui import decal_editor
        pane = self.panel
        if pane._decal_grab is None:
            return
        pane._decal_apply(decal_editor.roll(pane._decal_grab, d_body))

    # -- Scale ---------------------------------------------------------
    def scale_kind(self):
        """("decal", [Width, Depth]); Width is aspect-locked to the mask."""
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import DEPTH_STEP_SCALE, DecalsPaneMixin
        p = self._placement()
        if p is None:
            return "decal", []
        return "decal", [{"label": "Width", "value": decal_editor.width(p),
                          "step_scale": DecalsPaneMixin._decal_coord_step_scale()},
                         {"label": "Depth", "value": p.depth,
                          "step_scale": DEPTH_STEP_SCALE}]

    def scale_spec(self):
        if self._placement() is None:
            return None
        kind, fields = self.scale_kind()
        return {"kind": kind, "fields": fields}

    def get_scale(self):
        return tuple(f["value"] for f in self.scale_kind()[1])

    def set_scale_field(self, index, value) -> None:
        """Width (0, aspect-locked to the mask) or Depth (1), floored at
        MIN_DEPTH. The value a field already has is a no-op."""
        from dataclasses import replace
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import MIN_DEPTH
        p = self._placement()
        if p is None or not math.isfinite(value):
            return
        if index == 0:
            if value == decal_editor.width(p):
                return
            w = max(MIN_DEPTH, value)
            p = decal_editor.set_width(
                p, w, self.panel._decal_aspect(decal_editor.mask_of(p)))
        elif index == 1:
            if value == p.depth:
                return
            p = replace(p, depth=max(MIN_DEPTH, value))
        else:
            return
        self.panel._decal_apply(p)

    def scale_drag_begin(self, axis: int):
        p = self._placement()
        if p is not None:
            self.panel._decal_grab = p
        return None

    def scale_drag_apply(self, state, ratio: float) -> None:
        from dataclasses import replace
        from engine.ui import decal_editor
        pane = self.panel
        g = pane._decal_grab
        if g is None:
            return
        ratio = max(ratio, 1e-3)
        # Spec S3: uniform, "aspect locked to the mask" -- width scales by the
        # factor and the height snaps to the previewed mask's aspect (2:1
        # without a PNG), like the Width nudge. Depth still scales with it.
        p = decal_editor.set_width(g, decal_editor.width(g) * ratio,
                                   pane._decal_aspect(decal_editor.mask_of(g)))
        pane._decal_apply(replace(p, depth=g.depth * ratio))

    # -- Mirror --------------------------------------------------------
    def mirror_position(self) -> None:
        pass            # the per-panel coord Mirror: hidden for a decal

    def mirror(self) -> None:
        """Mirror Element: a NEW placement `<mask>_N` reflected across
        X = 0, which becomes the selection. Reflect origin/u/v/normal, then
        negate u and start from the reflected old far corner, so
        (u x v) . n < 0 still holds (readable from outside). Refused inline
        at the 16-placement cap."""
        from dataclasses import replace
        from engine.ui import decal_editor
        from engine.ui.spv_decals_pane import MAX_DECALS
        pane = self.panel
        p = self._placement()
        if p is None:
            return
        if pane._decal_count() >= MAX_DECALS:
            pane._decal_error = "Mirror refused: 16 placements is the maximum"
            return
        fx = lambda v: (-v[0], v[1], v[2])
        o, u, v, n = fx(p.origin), fx(p.u_axis), fx(p.v_axis), fx(p.normal)
        new_origin = (o[0] + u[0], o[1] + u[1], o[2] + u[2])
        new_u = (-u[0], -u[1], -u[2])
        mask = decal_editor.mask_of(p)
        name = pane._decal_auto_name(mask)
        # "" when the name IS the mask: no redundant "mask" key (as Add).
        q = replace(p, name=name, mask="" if name == mask else mask,
                    origin=new_origin, u_axis=new_u, v_axis=v, normal=n)
        pane._decal_working.append(q)
        pane._decal_selected = name
        pane._decal_reposition = False
        pane._decal_error = None
        pane._last_pushed = None
        pane._decal_sync_override()


_ADAPTERS = {
    "subsystem": MountTarget,
    "light": LightTarget,
    "emitter": EmitterTarget,
    "part_anchor": PartAnchorTarget,
    "part_pose": PartPoseTarget,
    "decal": DecalTarget,
}


def edit_target_for_key(panel, key):
    """The adapter for an explicit target tuple (as `_active_transform_target`
    returns), or None for None / an unknown kind."""
    if key is None:
        return None
    cls = _ADAPTERS.get(key[0])
    return cls(panel, key) if cls is not None else None


def edit_target_for(panel):
    """The adapter for `panel`'s one live transform target, or None. Built
    fresh on every call -- never cache it (a part pose's key carries its
    state). A selected decal in the active Decals pane wins (selecting one
    clears every other selection, and vice versa)."""
    if panel._decal_target() is not None:
        return DecalTarget(panel, ("decal", panel._decal_selected))
    return edit_target_for_key(panel, panel._active_transform_target())
