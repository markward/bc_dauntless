"""Per-kind edit targets for the Ship Property Viewer's editing tools.

Spec: docs/superpowers/specs/2026-09-29-spv-edit-target-refactor-design.md
(section 3). Every SPV tool -- Move, Rotate, Scale, their Copy/Paste,
Mirror, Pipette and the gizmo drags -- is to be written once against an
`EditTarget`: a thin view over `ShipPropertyViewerPanel`'s staged-edit
state for ONE selected thing (a subsystem mount, a light volume, an
emitter, a part anchor or pose, or a decal). An adapter owns no state, so
staging, undo snapshots and Save are unchanged.

A capability a kind lacks is `None` / empty / a no-op here. This module is
the interface skeleton only (plan Task 1); the per-kind adapters and
`edit_target_for` arrive in Task 2, and nothing imports it yet.
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

def edit_target_for(panel):  # filled in Task 2
    return None
