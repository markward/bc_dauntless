"""Binding-level tests for _dauntless_host.load_model's `scale` parameter
(Task 4 of the rock-catalogue plan): scale is folded into the model's dedupe
identity and baked into vertex positions for glTF loads.
"""
import base64
import json
import os
import struct

import pytest


def _write_cube_gltf(tmp_path, half_m):
    """Mirror native/tests/assets/cpu/gltf_fixture.h:write_cube_fixture --
    a closed, 12-triangle cube (2 tris/face), CCW outward-facing winding, in
    glTF metres, centred on the origin with half-extent `half_m`. POSITION
    only (no NORMAL/TEXCOORD); the loader derives flat per-triangle normals.
    """
    h = half_m
    corners = [
        (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
        (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h),
    ]
    buf = b"".join(struct.pack("<3f", *c) for c in corners)
    pos_bytes = len(buf)  # 8 * 3 * 4 = 96

    idx = [
        0, 3, 2, 0, 2, 1,   # -Z
        4, 5, 6, 4, 6, 7,   # +Z
        0, 1, 5, 0, 5, 4,   # -Y
        2, 3, 7, 2, 7, 6,   # +Y
        0, 4, 7, 0, 7, 3,   # -X
        1, 2, 6, 1, 6, 5,   # +X
    ]
    buf += struct.pack("<%dH" % len(idx), *idx)
    idx_bytes = len(buf) - pos_bytes  # 36 * 2 = 72

    data_uri = "data:application/octet-stream;base64," + base64.b64encode(buf).decode("ascii")
    prim = {"attributes": {"POSITION": 0}, "indices": 1}
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(buf), "uri": data_uri}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": pos_bytes},
            {"buffer": 0, "byteOffset": pos_bytes, "byteLength": idx_bytes},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": [-h, -h, -h], "max": [h, h, h]},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [prim]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    p = tmp_path / "cube.gltf"
    p.write_text(json.dumps(doc))
    return p


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(64, 64, "load-model-scale-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield _dauntless_host
    finally:
        _dauntless_host.shutdown()


def test_scale_gives_distinct_handles_and_scaled_aabb(host, tmp_path):
    p = _write_cube_gltf(tmp_path, half_m=1.75)  # half-extent 1 model unit
    a = host.load_model(str(p), [str(tmp_path)], None, None, 1.0)
    b = host.load_model(str(p), [str(tmp_path)], None, None, 2.0)
    assert a != b
    (_, ha), (_, hb) = host.model_aabb(a), host.model_aabb(b)
    assert abs(hb[0] - 2.0 * ha[0]) < 1e-4
    assert abs(ha[0] - 1.0) < 1e-4


def test_same_scale_dedupes(host, tmp_path):
    p = _write_cube_gltf(tmp_path, half_m=1.75)
    assert host.load_model(str(p), [str(tmp_path)], None, None, 0.5) == \
        host.load_model(str(p), [str(tmp_path)], None, None, 0.5)


def test_renderer_wrapper_passes_scale(monkeypatch):
    from engine import renderer

    seen = {}

    class H:
        def load_model(self, *a):
            seen["args"] = a
            return 7

    monkeypatch.setattr(renderer, "_h", H())
    assert renderer.load_model("x.gltf", ["d"], scale=0.25) == 7
    # args: (nif_path, texture_search_path, texture_replacements, decals,
    # scale, geosphere) -- geosphere is the new trailing arg (Task 3 of the
    # planet-geosphere plan), so scale is now second-to-last.
    assert seen["args"][-2] == 0.25
    assert seen["args"][-1] is False
