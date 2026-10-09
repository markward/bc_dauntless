"""Bridge editor picking and shape identity (spec 2026-10-08-bridge-emitters §4).

A pick is the ray through the cursor of the camera ACTUALLY drawn (the fly
camera while the editor is open), traced against the bridge instance. A shape's
identity across launches is (NIF content hash, block index, shape name)."""
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


def pick_mesh(trace, cursor_xy, viewport, pose, exclude=()) -> Optional[int]:
    """Mesh index under `cursor_xy` (framebuffer pixels, top-left origin) for
    the camera `pose` = (eye, target, up, fov_y_rad), or None."""
    if viewport[0] <= 0 or viewport[1] <= 0:
        return None
    eye, target, up, fov = pose
    ray = cursor_ray(cursor_xy, viewport, AimCamera(eye, target, up, fov, NEAR, FAR))
    if ray is None:
        return None
    origin, direction = ray
    hit = trace(origin, direction, MAX_PICK_DIST, tuple(exclude))
    if hit is None:
        return None
    return int(hit[3])


def identity_for(model_info, mesh, textures_by_block) -> Optional[ShapeIdentity]:
    """Resolve a mesh index to its ShapeIdentity; None if the mesh is unknown
    or was not built from a NIF shape (block < 0)."""
    for m in model_info.get("meshes", ()):
        if m["mesh"] != mesh:
            continue
        if m["block"] < 0:
            return None
        return ShapeIdentity(
            mesh=int(mesh), block=int(m["block"]), name=str(m["name"]),
            node_chain=tuple(m["node_chain"]),
            textures=tuple(textures_by_block.get(m["block"], ())),
            content_hash=str(model_info.get("content_hash", "")))
    return None


class PickCycle:
    """Alt+click = the surface behind: at the same spot, exclude every mesh
    already picked there; a click anywhere else starts again."""

    def __init__(self):
        self._xy = None
        self._excluded = ()

    def reset(self):
        self._xy = None
        self._excluded = ()

    def next_exclusion(self, cursor_xy, current_mesh, slop_px=4.0) -> tuple:
        if current_mesh < 0:
            self.reset()
            return ()
        same = (self._xy is not None
                and abs(cursor_xy[0] - self._xy[0]) <= slop_px
                and abs(cursor_xy[1] - self._xy[1]) <= slop_px)
        if not same:
            self._excluded = ()
        self._xy = (cursor_xy[0], cursor_xy[1])
        if current_mesh not in self._excluded:
            self._excluded = self._excluded + (current_mesh,)
        return self._excluded
