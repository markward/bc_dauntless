"""Classify a Blender-authored mesh's edges hard/soft from its corner normals."""
from dataclasses import dataclass

NORMAL_TOL = 1e-4


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
