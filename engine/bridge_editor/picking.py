"""Bridge editor picking and shape identity (spec 2026-10-08-bridge-emitters §4).

A pick is the ray through the cursor of the camera ACTUALLY drawn (the fly
camera while the editor is open), traced against the bridge instance. A shape's
identity across launches is (NIF content hash, block index, shape name). Stock
DBridge's shapes are all unnamed, so there the identity is effectively (hash,
block) and the DISPLAY name falls back to the owning node's name."""
from dataclasses import dataclass
from typing import Optional

from engine.manual_aim import AimCamera, cursor_ray

MAX_PICK_DIST = 2000.0
NEAR = 1.0      # _BridgeCamera.NEAR
FAR = 800.0     # _BridgeCamera.FAR


@dataclass(frozen=True)
class ShapeIdentity:
    mesh: int
    block: int
    name: str
    node_chain: tuple
    textures: tuple
    content_hash: str

    @property
    def key(self) -> str:
        return f"{self.block}:{self.name}"

    @property
    def display_name(self) -> str:
        """The shape name; for an unnamed shape, "(node) <owning node>" --
        the last named entry of node_chain. Display only: the key keeps the
        real (possibly empty) name."""
        if self.name:
            return self.name
        for node in reversed(self.node_chain):
            if node:
                return f"(node) {node}"
        return "(unnamed)"


def pick_hit(trace, cursor_xy, viewport, pose, exclude=()) -> Optional[tuple]:
    """Full trace result (point, normal, distance, mesh, material) under
    `cursor_xy` (framebuffer pixels, top-left origin) for the camera `pose` =
    (eye, target, up, fov_y_rad), or None. Same ray as pick_mesh -- use this
    when the hit point/normal are also needed (placing a light), not just
    the mesh index."""
    if viewport[0] <= 0 or viewport[1] <= 0:
        return None
    eye, target, up, fov = pose
    ray = cursor_ray(cursor_xy, viewport, AimCamera(eye, target, up, fov, NEAR, FAR))
    if ray is None:
        return None
    origin, direction = ray
    return trace(origin, direction, MAX_PICK_DIST, tuple(exclude))


def pick_mesh(trace, cursor_xy, viewport, pose, exclude=()) -> Optional[int]:
    """Mesh index under `cursor_xy` (framebuffer pixels, top-left origin) for
    the camera `pose` = (eye, target, up, fov_y_rad), or None."""
    hit = pick_hit(trace, cursor_xy, viewport, pose, exclude)
    if hit is None:
        return None
    return int(hit[3])


def identity_for(model_info, mesh) -> Optional[ShapeIdentity]:
    """Resolve a mesh index to its ShapeIdentity; None if the mesh is unknown
    or was not built from a NIF shape (block < 0). Textures come from the
    mesh entry (host_io.model_identity: the Base texture as BUILT)."""
    for m in model_info.get("meshes", ()):
        if m["mesh"] != mesh:
            continue
        if m["block"] < 0:
            return None
        return ShapeIdentity(
            mesh=int(mesh), block=int(m["block"]), name=str(m["name"]),
            node_chain=tuple(m["node_chain"]),
            textures=tuple(m.get("textures", ())),
            content_hash=str(model_info.get("content_hash", "")))
    return None


class PickCycle:
    """Alt+click = the surface behind what is under the cursor.

    At a spot different from the last Alt+click, pick the FRONT surface first
    (no exclusion), exclude it, and pick again -- so the first Alt+click
    always returns the surface behind, whatever was selected before.
    Repeated Alt+clicks at the same spot exclude every mesh already passed
    there and step deeper. A plain click (reset) starts again."""

    def __init__(self):
        self._xy = None
        self._excluded = ()

    def reset(self):
        self._xy = None
        self._excluded = ()

    def alt_pick(self, pick, cursor_xy, slop_px=4.0) -> Optional[int]:
        """`pick(exclude) -> mesh or None` traces the ray under `cursor_xy`."""
        same = (self._xy is not None
                and abs(cursor_xy[0] - self._xy[0]) <= slop_px
                and abs(cursor_xy[1] - self._xy[1]) <= slop_px)
        if not same:
            self._xy = (cursor_xy[0], cursor_xy[1])
            front = pick(())
            self._excluded = () if front is None else (front,)
            if front is None:
                return None
        hit = pick(self._excluded)
        if hit is not None and hit not in self._excluded:
            self._excluded = self._excluded + (hit,)
        return hit
