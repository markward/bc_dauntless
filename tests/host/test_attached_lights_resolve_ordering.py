"""Source-level ordering guard for attached dynamic lights.

`resolve_attached_dynamic_lights` rewrites body-frame lights to world space
through each instance's CURRENT `world` matrix. That is only the hull's
matrix if it runs AFTER `sync_instance_transforms_from_store()` (which
recomposes every store-bound instance at the top of frame()) and never at
`set_dynamic_lights` time (which would read last frame's matrices — the
hull/light jitter this feature removes). frame() lives in the pybind host
and needs a GL window, so this is a source-order guard in the style of
tests/host/test_camera_dt_wiring.py.
"""
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "native" / "src" / "host" / "host_bindings.cc"


def _frame_body() -> str:
    src = _SRC.read_text()
    # The sweep call inside frame() is the one preceded by the xform_sync scope.
    m = re.search(r'DAUNTLESS_FRAME_SCOPE\("xform_sync"\);(.*?)DAUNTLESS_FRAME_SCOPE\("anim"\)',
                  src, re.S)
    assert m, "frame()'s xform_sync scope not found"
    return m.group(1)


def test_resolve_runs_inside_xform_sync_after_the_store_sweep():
    body = _frame_body()
    sweep = body.find("sync_instance_transforms_from_store();")
    resolve = body.find("renderer::resolve_attached_dynamic_lights(g_world, g_dynamic_lights);")
    assert sweep >= 0, "store sweep missing from xform_sync scope"
    assert resolve >= 0, "resolve_attached_dynamic_lights not called in xform_sync scope"
    assert resolve > sweep, "resolve must run AFTER the store sweep"


def test_resolve_is_not_called_from_the_set_dynamic_lights_binding():
    src = _SRC.read_text()
    start = src.find('m.def("set_dynamic_lights"')
    assert start >= 0
    end = src.find("m.def(", start + 1)
    binding = src[start:end]
    assert "resolve_attached_dynamic_lights" not in binding
