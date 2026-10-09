"""Encoder for the opaque shape-edit payload (spec §6.1). Always writes
"BSD2"; the C++ decoder (native/src/assets/src/mesh_fix.cc:
decode_shape_edits) still reads BSD1 too. Both sides are pinned by the same
golden blob in their tests.

BSD2 positions and UVs are either a literal (geometry Mark authored) or a
`Ref` to an ORIGINAL vertex of some NiTriShape -- so a vertex snapped onto a
BC vertex is stored as an index, never as BC's coordinate (spec §6.2)."""
import base64
import math
import struct
from dataclasses import dataclass

from tools.shape_diff import ShapeDiffError

_MAGIC = b"BSD2"
_LITERAL, _REF = 0, 1


@dataclass(frozen=True)
class Ref:
    """A reference to ORIGINAL vertex `vertex` of the NiTriShape at block
    `block`: its position (transformed into the target shape's frame by the
    loader) or its UV0 -- never a copied value (spec §6.2)."""
    block: int
    vertex: int


def _u16(n: int, what: str) -> bytes:
    if not 0 <= n <= 0xFFFF:
        raise ShapeDiffError(f"{what} {n} does not fit in 16 bits")
    return struct.pack("<H", n)


def _ref(r: Ref, what: str) -> bytes:
    if not 0 <= r.block <= 0xFFFFFFFF:
        raise ShapeDiffError(f"{what} reference block {r.block} does not fit in 32 bits")
    return struct.pack("<BI", _REF, r.block) + _u16(r.vertex, f"{what} reference vertex")


def _literal(v, n: int, what: str) -> bytes:
    if not isinstance(v, (tuple, list)) or len(v) != n:
        raise ShapeDiffError(f"{what} {v!r} is neither a Ref nor {n} floats")
    if not all(math.isfinite(c) for c in v):
        raise ShapeDiffError(f"{what} {v!r} is not finite")
    return struct.pack(f"<B{n}f", _LITERAL, *v)


def _position(p) -> bytes:
    return _ref(p, "position") if isinstance(p, Ref) else _literal(p, 3, "position")


def _uv(uv) -> bytes:
    return _ref(uv, "uv") if isinstance(uv, Ref) else _literal(uv, 2, "uv")


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
            out += _u16(i, "move index") + _position(p)
        for i, uv in uvs:
            out += _u16(i, "uv index") + _uv(uv)
        for v in addv:
            if "attr_src" not in v:
                raise ShapeDiffError(
                    "added vertex has no attr_src (BSD2 copies colour/UV1 from an "
                    "original; literal BC attributes are never written)")
            out += _position(v["pos"]) + _uv(v["uv0"]) + _u16(v["attr_src"], "attr_src")
        for t in remt:
            out += _u16(t, "removed triangle")
        for t in addt:
            out += b"".join(_u16(i, "triangle index") for i in t)
    return bytes(out)


def encode_b64(edits: list) -> str:
    return base64.b64encode(encode(edits)).decode("ascii")
