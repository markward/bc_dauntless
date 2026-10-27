"""Classify a Blender-authored mesh's edges hard/soft from its corner normals."""
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


def _nearest(positions, applied, block):
    """Lowest applied index within POSITION_TOL per coordinate of each edit
    position (the applied shape may repeat a position, e.g. a UV seam)."""
    out = []
    for i, p in enumerate(positions):
        for j, q in enumerate(applied):
            if all(abs(a - b) <= POSITION_TOL for a, b in zip(p, q)):
                out.append(j)
                break
        else:
            raise ShapeDiffError(
                f"block {block}: edit vertex {i} {tuple(p)!r} matches no vertex of the applied shape")
    return out


def records(applied_shapes, edit_meshes):
    """One record per edited block with authored normals, sorted by block:
    {"block", "vertex_count", "hard", "soft", "ends"} over FINAL vertex
    indices (a < b). `ends[(a, b)]` = (normals agree at a, at b); it is for
    the verifier and never encoded."""
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
        verts = by_block[block]["vertices"]
        final = _nearest(mesh.positions, verts, block)
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
            seen[(a, b)] = (flag.hard, ends)
        keys = sorted(seen)
        out.append({
            "block": block,
            "vertex_count": len(verts),
            "hard": [k for k in keys if seen[k][0]],
            "soft": [k for k in keys if not seen[k][0]],
            "ends": {k: seen[k][1] for k in keys},
        })
    return out
