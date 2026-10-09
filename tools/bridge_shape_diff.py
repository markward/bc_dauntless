"""Shape-geometry diff for BC set NIFs: export to OBJ for Blender, diff an
edited export against an unaltered one, write ONLY the diff as a mesh fix.

Spec: docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md

    uv run python -m tools.bridge_shape_diff export --out <scratch dir>
    uv run python -m tools.bridge_shape_diff diff <base.obj> <edit.obj> [--write]

OBJ files contain BC geometry: keep them OUT of the repo. Blender: import the
OBJ into an EMPTY scene (delete Blender's default Cube/Camera/Light) with
default settings; export base.obj before editing and edit.obj after, both
with default settings. Don't join, split or rename objects. Accepted:
vertex MOVES, UV0 EDITS, deleted faces/vertices, added TRIANGLES whose
corners sit on existing vertices with existing UVs, and a new ALBEDO texture
per object (map_Kd; the .tga must be in the replacements overlay or stock
texture dir); new vertices are refused."""
import argparse
import json
import posixpath
import sys
from pathlib import Path

from engine import mods, paths
from tools.gen_mesh_fixes import fnv1a64_hex
from tools.shape_diff import ShapeDiffError, match, obj_io, payload

GENERATOR = "tools/bridge_shape_diff.py"
DEFAULT_NIF = "data/Models/Sets/DBridge/Dbridge.NIF"


def _nif_path(rel: str) -> Path:
    # Stock only (name-cut spec §10.3): never paths.game_asset, which prefers mods.
    return paths.game_root() / rel


def _shapes(rel: str):
    import _dauntless_host
    shapes = _dauntless_host.nif_shapes(str(_nif_path(rel)))
    if shapes is None:
        raise ShapeDiffError(f"cannot read {_nif_path(rel)}")
    return shapes


def _fix_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "native" / "assets" / "mesh_fixes"


def export(rel: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(rel).stem
    tex_dir = _nif_path(rel).parent / "High"

    def texture_path_for(name):
        p = tex_dir / name
        return p if p.exists() else None

    obj = out_dir / f"{stem}.obj"
    obj_io.write_obj(_shapes(rel), obj, out_dir / f"{stem}.mtl", texture_path_for)
    return obj


def _texture_dirs(rel: str) -> list:
    """Where a texture op's file must exist: the replacements overlay dir
    mirroring the NIF's texture dir, then the stock one (spec §5.3). Mod dirs
    are deliberately absent -- the fix applies with or without a mod."""
    tex_rel = posixpath.dirname(rel) + "/High"
    return [mods.replacements_root() / tex_rel, paths.game_root() / tex_rel]


def _has_geometry(e: dict) -> bool:
    return any(e.get(k) for k in ("moves", "uvs", "add_vertices",
                                  "remove_triangles", "add_triangles"))


def make_fix_dict(rel: str, edits: list) -> dict:
    geometry = [e for e in edits if _has_geometry(e)]
    textures = sorted(({"block": e["block"], "albedo": e["albedo"]}
                       for e in edits if e.get("albedo")), key=lambda t: t["block"])
    fix = {"format": 1, "source": rel, "generator": GENERATOR}
    if geometry or not textures:
        fix["shape_edits"] = payload.encode_b64(geometry)
    if textures:
        fix["textures"] = textures
    return fix


def _by_ref(positions) -> str:
    n = sum(1 for p in positions if isinstance(p, payload.Ref))
    return f" ({n} by reference)" if n else ""


def _summary(e: dict) -> str:
    parts = []
    if _has_geometry(e):
        moves = e.get("moves", [])
        addv = e.get("add_vertices", [])
        parts.append(f"{len(moves)} vertices moved{_by_ref(p for _, p in moves)}, "
                     f"{len(e.get('uvs', []))} UVs changed, "
                     f"{len(e.get('remove_triangles', []))} triangles removed, "
                     f"{len(e.get('add_triangles', []))} added, "
                     f"{len(addv)} vertices added{_by_ref(v['pos'] for v in addv)}")
    if e.get("albedo"):
        parts.append(f"texture -> {e['albedo']}")
    return f"block {e['block']}: " + ", ".join(parts)


def fix_text(fix: dict) -> str:
    return json.dumps(fix, indent=2) + "\n"


def build_fix(rel: str, base_path: Path, edit_path: Path, partial: bool = False):
    base_objs = obj_io.read_objects(base_path)
    edit_objs = obj_io.read_objects(edit_path)
    dirs = _texture_dirs(rel)
    if partial:
        edits, skipped = match.diff(_shapes(rel), base_objs, edit_objs, partial=True,
                                    texture_dirs=dirs)
        return make_fix_dict(rel, edits), edits, skipped
    edits = match.diff(_shapes(rel), base_objs, edit_objs, texture_dirs=dirs)
    return make_fix_dict(rel, edits), edits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bridge_shape_diff")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--nif", default=DEFAULT_NIF)
    df = sub.add_parser("diff")
    df.add_argument("base", type=Path)
    df.add_argument("edit", type=Path)
    df.add_argument("--nif", default=DEFAULT_NIF)
    df.add_argument("--write", action="store_true")
    df.add_argument("--partial", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            print(export(a.nif, a.out))
            return 0
        if a.partial:
            fix, edits, skipped = build_fix(a.nif, a.base, a.edit, partial=True)
        else:
            fix, edits = build_fix(a.nif, a.base, a.edit)
            skipped = []
        for e in edits:
            print(_summary(e))
        if skipped:
            print("skipped (not yet supported):")
            for name, reason in skipped:
                print(f"  {name}: {reason}")
        if not edits:
            print("no changes")
            return 0
        target = _fix_dir() / (fnv1a64_hex(_nif_path(a.nif).read_bytes()) + ".json")
        if target.exists() and json.loads(target.read_text()).get("generator") != GENERATOR:
            raise ShapeDiffError(f"{target.name} is owned by another generator; refusing to overwrite")
        if a.write:
            target.write_text(fix_text(fix))
            print(f"wrote {target}")
        else:
            print(f"dry run; --write to write {target}")
        return 0
    except ShapeDiffError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
