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
lock) through the adapters; the other tools and decals migrate in later
tasks.
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
