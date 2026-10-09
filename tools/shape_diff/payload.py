"""Encoder for the opaque "BSD1" shape-edit payload (spec §6.1). The C++
decoder is native/src/assets/src/mesh_fix.cc:decode_shape_edits; both are
pinned by the same golden blob in their tests."""
import base64
import struct

from tools.shape_diff import ShapeDiffError

_MAGIC = b"BSD1"


def _u16(n: int, what: str) -> bytes:
    if not 0 <= n <= 0xFFFF:
        raise ShapeDiffError(f"{what} {n} does not fit in 16 bits")
    return struct.pack("<H", n)


def encode(edits: list) -> bytes:
    out = bytearray(_MAGIC)
    out += _u16(len(edits), "shape count")
    for e in edits:
        moves = e.get("moves", [])
        uvs = e.get("uvs", [])
        addv = e.get("add_vertices", [])
        remt = e.get("remove_triangles", [])
        addt = e.get("add_triangles", [])
        out += struct.pack("<I", e["block"])
        out += _u16(e["orig_vertex_count"], "vertex count")
        out += _u16(e["orig_triangle_count"], "triangle count")
        for n, what in ((moves, "moves"), (uvs, "uvs"), (addv, "added vertices"),
                        (remt, "removed triangles"), (addt, "added triangles")):
            out += _u16(len(n), what)
        for i, p in moves:
            out += _u16(i, "move index") + struct.pack("<3f", *p)
        for i, uv in uvs:
            out += _u16(i, "uv index") + struct.pack("<2f", *uv)
        for v in addv:
            out += struct.pack("<11f", *v["pos"], *v["uv0"], *v["uv1"], *v["color"])
        for t in remt:
            out += _u16(t, "removed triangle")
        for t in addt:
            out += b"".join(_u16(i, "triangle index") for i in t)
    return bytes(out)


def encode_b64(edits: list) -> str:
    return base64.b64encode(encode(edits)).decode("ascii")
