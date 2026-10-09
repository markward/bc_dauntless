"""Shape-geometry diff for BC set NIFs: export to OBJ for Blender, diff an
edited export against an unaltered one, write ONLY the diff as a mesh fix.

Spec: docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md

    uv run python -m tools.bridge_shape_diff export --out <scratch dir>
    uv run python -m tools.bridge_shape_diff diff <base.obj> <edit.obj> [--write]

OBJ files contain BC geometry: keep them OUT of the repo. Blender: import the
OBJ into an EMPTY scene (delete Blender's default Cube/Camera/Light) with
default settings; export base.obj before editing and edit.obj after, both
with default settings. Don't join, split or rename objects. Iteration 1
accepts vertex MOVES and UV0 EDITS; topology changes are refused."""
import argparse
import json
import sys
from pathlib import Path

from engine import paths
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


def make_fix_dict(rel: str, edits: list) -> dict:
    return {"format": 1, "source": rel, "generator": GENERATOR,
            "shape_edits": payload.encode_b64(edits)}


def fix_text(fix: dict) -> str:
    return json.dumps(fix, indent=2) + "\n"


def build_fix(rel: str, base_path: Path, edit_path: Path, partial: bool = False):
    base_objs = obj_io.read_objects(base_path)
    edit_objs = obj_io.read_objects(edit_path)
    if partial:
        edits, skipped = match.diff(_shapes(rel), base_objs, edit_objs, partial=True)
        return make_fix_dict(rel, edits), edits, skipped
    edits = match.diff(_shapes(rel), base_objs, edit_objs)
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
            print(f"block {e['block']}: {len(e['moves'])} vertices moved, "
                  f"{len(e['uvs'])} UVs changed")
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
