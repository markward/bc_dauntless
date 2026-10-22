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
        raise ShapeDiffError(
            f"object {name!r} is not a shape export (expected b<block>_...) -- "
            "import the OBJ into an EMPTY scene (delete Blender's default Cube/Camera/Light)")
    return int(m.group(1))


def _mat_name(shape: dict) -> str:
    tex = shape.get("textures") or []
    if not tex:
        return "none"
    base = re.split(r"[/\\]", tex[0])[-1]
    return re.sub(r"\s+", "_", base)


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
    obj_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    mtl = []
    for mat, tex in mats.items():
        mtl += [f"newmtl {mat}", "Kd 1 1 1"]
        path = texture_path_for(tex) if tex else None
        if path is not None:
            mtl.append(f"map_Kd {path}")
    mtl_path.write_text("\n".join(mtl) + "\n", encoding="utf-8", newline="\n")


@dataclass
class ObjMesh:
    positions: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    # Parallel to `faces`: the map_Kd BASENAME of the material in effect for
    # each face (None: no material, no map_Kd, or no readable .mtl). Empty
    # for a mesh built by hand -- callers treat that as "no texture info".
    face_albedos: list = field(default_factory=list)


def _map_kd_basename(rest: str):
    """Basename of a map_Kd argument string, skipping any leading options
    ("-bm 1.0", "-s 1 1 1") Blender or another exporter may write."""
    toks = rest.split()
    while toks and toks[0].startswith("-"):
        toks = toks[1:]
        while toks:
            try:
                float(toks[0])
            except ValueError:
                break
            toks = toks[1:]
    path = " ".join(toks)
    base = re.split(r"[/\\]", path)[-1]
    return base or None


def read_mtl(path: Path) -> dict:
    """material name -> map_Kd file basename (None when it has no map_Kd).
    Compare by basename, never by material name: Blender renames materials
    ('.001') and the directory differs between source trees."""
    out = {}
    current = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        if parts[0] == "newmtl":
            current = parts[1].strip() if len(parts) > 1 else ""
            out[current] = None
        elif parts[0] == "map_Kd" and current is not None and len(parts) > 1:
            out[current] = _map_kd_basename(parts[1])
    return out


def read_objects(path: Path) -> dict:
    objs = {}
    owner = []          # global v index -> (mesh, local index)
    uvs = []
    current = None
    mtl = {}            # material name -> map_Kd basename, from mtllib
    material = None     # usemtl in effect
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "mtllib":
            mtl_path = Path(path).parent / " ".join(parts[1:])
            if not mtl_path.is_file():
                # File-level: without it every texture compare is wrong (a
                # missing BASE .mtl would make every textured object "new").
                raise ShapeDiffError(
                    f"{Path(path).name} names mtllib {mtl_path}, which is missing -- "
                    "export the .mtl beside the .obj")
            mtl = read_mtl(mtl_path)
        elif tag == "usemtl":
            material = " ".join(parts[1:])
        elif tag == "o":
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
                if not 0 <= vi < len(owner):
                    raise ShapeDiffError(f"line {line_no}: vertex index out of range")
                mesh, local = owner[vi]
                if mesh is not current:
                    raise ShapeDiffError("face references another object's vertex")
                uv = None
                if len(fields) > 1 and fields[1]:
                    ti = int(fields[1])
                    ti = ti - 1 if ti > 0 else len(uvs) + ti
                    if not 0 <= ti < len(uvs):
                        raise ShapeDiffError(f"line {line_no}: uv index out of range")
                    uv = uvs[ti]
                face.append((local, uv))
            current.faces.append(face)
            current.face_albedos.append(mtl.get(material))
    return objs
