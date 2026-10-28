"""Classify a Blender-authored mesh's edges hard/soft from its corner normals."""
import itertools
import math
from dataclasses import dataclass

from tools.shape_diff import ShapeDiffError

NORMAL_TOL = 1e-4
# Blender's OBJ export rounds positions; the applied shape is the same mesh.
POSITION_TOL = 1.5 / 1024


@dataclass(frozen=True)
class EdgeFlag:
    hard: bool
    same_a: bool
    same_b: bool


def _agree(n1, n2) -> bool:
    return all(abs(a - b) <= NORMAL_TOL for a, b in zip(n1, n2))


def edge_flags(mesh):
    """None when any corner lacks a normal (object not authored); else
    {(va, vb): EdgeFlag} (va < vb) for every edge used by exactly two faces."""
    if not mesh.face_normals or len(mesh.face_normals) != len(mesh.faces):
        return None
    edges = {}
    for face, normals in zip(mesh.faces, mesh.face_normals):
        if any(n is None for n in normals):
            return None
        k = len(face)
        for i in range(k):
            a, b = face[i][0], face[(i + 1) % k][0]
            if a == b:
                continue
            na, nb = normals[i], normals[(i + 1) % k]
            if a > b:
                a, b, na, nb = b, a, nb, na
            edges.setdefault((a, b), []).append((na, nb))
    out = {}
    for key, uses in edges.items():
        if len(uses) != 2:
            continue
        (a1, b1), (a2, b2) = uses
        same_a, same_b = _agree(a1, a2), _agree(b1, b2)
        out[key] = EdgeFlag(not (same_a and same_b), same_a, same_b)
    return out


def _cell(p):
    return tuple(math.floor(c / POSITION_TOL) for c in p)


def _nearest(positions, applied, block, needed):
    """{edit vertex: nearest applied index within POSITION_TOL per coordinate}
    for the `needed` edit vertices, ties to the lowest index (the applied
    shape may repeat a position, e.g. a UV seam). A grid of POSITION_TOL
    cells keeps it linear."""
    grid = {}
    for j, q in enumerate(applied):
        grid.setdefault(_cell(q), []).append(j)
    out = {}
    for i in sorted(needed):
        p = positions[i]
        cx, cy, cz = _cell(p)
        best = None
        for dx, dy, dz in itertools.product((-1, 0, 1), repeat=3):
            for j in grid.get((cx + dx, cy + dy, cz + dz), ()):
                q = applied[j]
                if not all(abs(a - b) <= POSITION_TOL for a, b in zip(p, q)):
                    continue
                key = (sum((a - b) ** 2 for a, b in zip(p, q)), j)
                if best is None or key < best:
                    best = key
        if best is None:
            raise ShapeDiffError(
                f"block {block}: edit vertex {i} {tuple(p)!r} matches no vertex of the applied shape")
        out[i] = best[1]
    return out


def _record(block, mesh, flags, verts):
    final = _nearest(mesh.positions, verts, block,
                     {v for key in flags for v in key})
    seen = {}
    for (va, vb), flag in flags.items():
        a, b = final[va], final[vb]
        if a == b:
            continue
        ends = (flag.same_a, flag.same_b)
        if a > b:
            a, b, ends = b, a, ends[::-1]
        old = seen.get((a, b))
        if old is not None and old[0] != flag.hard:
            raise ShapeDiffError(
                f"block {block}: conflicting hard/soft flags on edge ({a}, {b})")
        if old is not None and old[1] != ends:
            raise ShapeDiffError(
                f"block {block}: conflicting ends on edge ({a}, {b})")
        seen[(a, b)] = (flag.hard, ends)
    keys = sorted(seen)
    return {
        "block": block,
        "vertex_count": len(verts),
        "hard": [k for k in keys if seen[k][0]],
        "soft": [k for k in keys if not seen[k][0]],
        "ends": {k: seen[k][1] for k in keys},
    }


def records(applied_shapes, edit_meshes, skipped=None):
    """One record per edited block with authored normals, sorted by block:
    {"block", "vertex_count", "hard", "soft", "ends"} over FINAL vertex
    indices (a < b). `ends[(a, b)]` = (normals agree at a, at b); it is for
    the verifier and never encoded. A block whose record cannot be built
    raises, unless `skipped` is a list: then (block, reason) is appended to
    it and the block gets no record."""
    by_block = {s["block"]: s for s in applied_shapes}
    for block in edit_meshes:
        if block not in by_block:
            raise ShapeDiffError(f"block {block}: no such shape in the applied shapes")
    out = []
    for block in sorted(edit_meshes):
        mesh = edit_meshes[block]
        flags = edge_flags(mesh)
        if flags is None:
            continue
        try:
            out.append(_record(block, mesh, flags, by_block[block]["vertices"]))
        except ShapeDiffError as err:
            if skipped is None:
                raise
            skipped.append((block, str(err)))
    return out
