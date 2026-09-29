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
clipboard kind, gizmo, handle drag); the other tools and decals migrate in
later tasks.
"""


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
    # Rotate
    def rotate_spec(self): return None           # dict {fields, clipboard_kind} | None
    def get_rotation(self): return None
    def set_rotation(self, value) -> None: pass
    def rotate_nudge(self, field: str, delta: float) -> None: pass
    def ring_drag_begin(self, *args): return None
    def ring_drag_apply(self, state, angle: float) -> None: pass
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
    def mirror(self) -> None: pass
    def pipette_fields_from(self, src: "EditTarget") -> tuple: return ()

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


class _PartNode(EditTarget):
    """A model part's Anchor or {State} Transformation node. Never locked:
    tuning the very pose you are looking at is the point."""

    def coord_kind(self) -> str:
        # A part anchor and a posed anchor only paste onto their own kind.
        return self.key[0]

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


_ADAPTERS = {
    "subsystem": MountTarget,
    "light": LightTarget,
    "emitter": EmitterTarget,
    "part_anchor": PartAnchorTarget,
    "part_pose": PartPoseTarget,
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
    state)."""
    return edit_target_for_key(panel, panel._active_transform_target())
