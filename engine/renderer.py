"""Pythonic wrapper around the _open_stbc_host extension module.

Re-exports the binding functions with type hints. Application code should
import from here, not from _open_stbc_host directly.
"""
from typing import Tuple

import _open_stbc_host as _h

InstanceId = _h.InstanceId


def init(width: int, height: int, title: str) -> None:
    _h.init(width, height, title)


def shutdown() -> None:
    _h.shutdown()


def should_close() -> bool:
    return _h.should_close()


def frame() -> None:
    _h.frame()


def load_model(nif_path: str, texture_search_path: str) -> int:
    return _h.load_model(nif_path, texture_search_path)


def create_instance(model: int) -> InstanceId:
    return _h.create_instance(model)


def destroy_instance(iid: InstanceId) -> None:
    _h.destroy_instance(iid)


def set_world_transform(iid: InstanceId, mat4_row_major: list) -> None:
    _h.set_world_transform(iid, mat4_row_major)


def set_visible(iid: InstanceId, visible: bool) -> None:
    _h.set_visible(iid, visible)


def set_camera(eye: Tuple[float, float, float],
               target: Tuple[float, float, float],
               up: Tuple[float, float, float],
               fov_y_rad: float, near: float, far: float) -> None:
    _h.set_camera(eye, target, up, fov_y_rad, near, far)


def set_lighting(ambient: Tuple[float, float, float],
                 directionals: list) -> None:
    """Configure the renderer's lighting state for subsequent frame()s.

    `directionals` is a list of ((dx, dy, dz), (r, g, b)) tuples where
    (dx, dy, dz) is the direction TOWARD the light source and (r, g, b)
    is the color × dimmer product. Up to 4 entries are honored;
    additional ones are silently dropped by the bindings.
    """
    _h.set_lighting(ambient, directionals)


def set_backdrops(backdrops: list) -> None:
    """Configure the renderer's ordered backdrop list. Each entry is a
    dict matching engine.appc.backdrops.aggregate_for_renderer's output:

        {
            "texture_path": str (absolute),
            "kind": "star" | "backdrop",
            "h_tile": float, "v_tile": float,
            "h_span": float, "v_span": float,
            "world_rotation": list[9],
            "target_poly_count": int,
        }
    """
    _h.set_backdrops(backdrops)
