"""Encoder for the opaque shape-edit payload (spec §6.1). Always writes
"BSD2"; the C++ decoder (native/src/assets/src/mesh_fix.cc:
decode_shape_edits) still reads BSD1 too. Both sides are pinned by the same
golden blob in their tests.

BSD2 positions are always a `Ref` to an ORIGINAL vertex of some NiTriShape,
optionally plus a target-local delta (kind 2) -- so a vertex snapped onto a
BC vertex is stored as an index, never as BC's coordinate, and an authored
position is an offset from an original (spec §6.2). UVs are a literal or a
`Ref`. The decoder still reads literal (kind 0) positions."""
import base64
import math
import struct
from dataclasses import dataclass

from tools.shape_diff import ShapeDiffError

_MAGIC = b"BSD2"
_LITERAL, _REF, _REF_DELTA = 0, 1, 2


@dataclass(frozen=True)
class Ref:
    """A reference to ORIGINAL vertex `vertex` of the NiTriShape at block
    `block`: its position (transformed into the target shape's frame by the
    loader) or its UV0 -- never a copied value (spec §6.2). A position may
    add `delta`, a TARGET-shape-local offset (kind 2)."""
    block: int
    vertex: int
    delta: tuple = None


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
    """Kind 1 (reference) or 2 (reference + delta). Never kind 0: a literal
    position would put a number in the payload that may be BC's (§6.2)."""
    if not isinstance(p, Ref):
        raise ShapeDiffError(
            f"literal position {p!r}: positions are always written relative to an original")
    if p.delta is None:
        return _ref(p, "position")
    out = bytearray(_ref(p, "position"))
    out[0] = _REF_DELTA
    return bytes(out) + _literal(p.delta, 3, "position delta")[1:]


def _uv(uv) -> bytes:
    if isinstance(uv, Ref) and uv.delta is not None:
        raise ShapeDiffError("a uv reference takes no delta")
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


def encode_smoothing(records: list) -> bytes:
    """BSM1: authored hard/soft edges per shape, over FINAL vertex indices
    (a < b, strictly ascending, no pair in both lists). Indices only -- no
    coordinate or normal."""
    out = [b"BSM1", _u16(len(records), "smoothing shape count")]
    for r in records:
        n = r["vertex_count"]
        if not 0 <= r["block"] <= 0xFFFFFFFF:
            raise ShapeDiffError(f"smoothing block {r['block']} does not fit in 32 bits")
        out.append(struct.pack("<I", r["block"]))
        out.append(_u16(n, "smoothing vertex count"))
        out.append(_u16(len(r["hard"]), "smoothing hard-edge count"))
        out.append(_u16(len(r["soft"]), "smoothing soft-edge count"))
        for pairs in (r["hard"], r["soft"]):
            prev = None
            for a, b in pairs:
                if not 0 <= a < b < n:
                    raise ShapeDiffError(
                        f"smoothing edge ({a}, {b}) is not ascending within {n} vertices")
                if prev is not None and (a, b) <= prev:
                    raise ShapeDiffError(
                        f"smoothing edge ({a}, {b}) is not strictly after ({prev[0]}, {prev[1]})")
                prev = (a, b)
                out.append(_u16(a, "smoothing edge") + _u16(b, "smoothing edge"))
        if set(r["hard"]) & set(r["soft"]):
            raise ShapeDiffError(f"smoothing block {r['block']} lists an edge as both hard and soft")
    return b"".join(out)


def encode_smoothing_b64(records: list) -> str:
    return base64.b64encode(encode_smoothing(records)).decode("ascii")


def decode_smoothing_b64(text: str) -> list:
    """Inverse of encode_smoothing_b64 (records without `ends`)."""
    raw = base64.b64decode(text)
    if raw[:4] != b"BSM1":
        raise ShapeDiffError("smoothing payload is not BSM1")
    (count,), at = struct.unpack_from("<H", raw, 4), 6
    out = []
    for _ in range(count):
        block, n, n_hard, n_soft = struct.unpack_from("<IHHH", raw, at)
        at += 10
        pairs = struct.unpack_from(f"<{2 * (n_hard + n_soft)}H", raw, at)
        at += 4 * (n_hard + n_soft)
        edges = list(zip(pairs[0::2], pairs[1::2]))
        out.append({"block": block, "vertex_count": n,
                    "hard": edges[:n_hard], "soft": edges[n_hard:]})
    return out
