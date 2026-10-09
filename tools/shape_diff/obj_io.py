"""OBJ/MTL writer and reader for shape diffs. The writer exports BC model
space with OBJ axes (x, z, -y) so Blender's DEFAULT import shows Z-up; the
reader undoes that. UV v is flipped (OBJ origin bottom-left, NIF top-left)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.shape_diff import ShapeDiffError, frames

WELD = 1024.0
_NAME_RE = re.compile(r"^b(\d{4,})_")


def object_name(shape: dict) -> str:
    label = re.sub(r"[^A-Za-z0-9]+", "_", shape.get("parent") or "").strip("_")
    name = f"b{shape['block']:04d}_{label}" if label else f"b{shape['block']:04d}"
    return name + "_hidden" if shape.get("hidden") else name


def block_of(name: str) -> int:
    m = _NAME_RE.match(name + "_")
    if not m:
        raise ShapeDiffError(f"object {name!r} is not a shape export (expected b<block>_...)")
    return int(m.group(1))


def _mat_name(shape: dict) -> str:
    tex = shape.get("textures") or []
    return re.sub(r"\s+", "_", tex[0]) if tex else "none"


def write_obj(shapes, obj_path: Path, mtl_path: Path, texture_path_for) -> None:
    lines = [f"mtllib {mtl_path.name}"]
    mats = {}
    v_base = vt_base = 0
    for s in shapes:
        weld, order = {}, []
        welded_of = []
        for i, p in enumerate(s["vertices"]):
            key = tuple(round(c * WELD) for c in p)
            if key not in weld:
                weld[key] = len(order)
                order.append(i)
            welded_of.append(weld[key])
        lines.append(f"o {object_name(s)}")
        cols = s.get("colors") or []
        for i in order:
            x, y, z = frames.bc_to_obj(s["vertices"][i])
            if cols:
                r, g, b, _ = cols[i]
                lines.append(f"v {x:.6f} {y:.6f} {z:.6f} {r:.6f} {g:.6f} {b:.6f}")
            else:
                lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for u, v in s["uvs"]:
            lines.append(f"vt {u:.6f} {1.0 - v:.6f}")
        mat = _mat_name(s)
        mats.setdefault(mat, (s.get("textures") or [None])[0])
        lines.append(f"usemtl {mat}")
        for t in s["triangles"]:
            w = [welded_of[k] for k in t]
            if len(set(w)) < 3:
                continue
            lines.append("f " + " ".join(f"{v_base + w[j] + 1}/{vt_base + t[j] + 1}"
                                         for j in range(3)))
        v_base += len(order)
        vt_base += len(s["uvs"])
    obj_path.write_text("\n".join(lines) + "\n")

    mtl = []
    for mat, tex in mats.items():
        mtl += [f"newmtl {mat}", "Kd 1 1 1"]
        path = texture_path_for(tex) if tex else None
        if path is not None:
            mtl.append(f"map_Kd {path}")
    mtl_path.write_text("\n".join(mtl) + "\n")


@dataclass
class ObjMesh:
    positions: list = field(default_factory=list)
    faces: list = field(default_factory=list)


def read_objects(path: Path) -> dict:
    objs = {}
    owner = []          # global v index -> (mesh, local index)
    uvs = []
    current = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "o":
            name = " ".join(parts[1:])
            current = objs.setdefault(name, ObjMesh())
        elif tag == "v":
            if current is None:
                raise ShapeDiffError("vertex before any 'o' line")
            p = tuple(float(c) for c in parts[1:4])
            owner.append((current, len(current.positions)))
            current.positions.append(frames.obj_to_bc(p))
        elif tag == "vt":
            u, v = float(parts[1]), float(parts[2])
            uvs.append((u, 1.0 - v))
        elif tag == "f":
            face = []
            for tok in parts[1:]:
                fields = tok.split("/")
                vi = int(fields[0])
                vi = vi - 1 if vi > 0 else len(owner) + vi
                mesh, local = owner[vi]
                if mesh is not current:
                    raise ShapeDiffError("face references another object's vertex")
                uv = None
                if len(fields) > 1 and fields[1]:
                    ti = int(fields[1])
                    uv = uvs[ti - 1 if ti > 0 else len(uvs) + ti]
                face.append((local, uv))
            current.faces.append(face)
    return objs
