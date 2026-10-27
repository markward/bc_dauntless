"""Shape-geometry diff for BC set NIFs: export to OBJ for Blender, diff an
edited export against an unaltered one, write ONLY the diff as a mesh fix.

Spec: docs/superpowers/specs/2026-10-09-bridge-shape-diff-design.md

    uv run python -m tools.bridge_shape_diff export --out <scratch dir>
    uv run python -m tools.bridge_shape_diff diff <base.obj> <edit.obj> [--write]

OBJ files contain BC geometry: keep them OUT of the repo. Blender: import the
OBJ into an EMPTY scene (delete Blender's default Cube/Camera/Light) with
default settings; export base.obj before editing and edit.obj after, both
with default settings. Don't join, split or rename objects. Accepted:
vertex MOVES, UV0 EDITS, deleted faces/vertices, NEW vertices, added faces
(n-gons are ear-clipped), and a new ALBEDO texture per object (map_Kd; the
.tga must be in the replacements overlay or stock texture dir; a map_Kd of
`<stem>_0.tga` with `<stem>_1.tga`, ... beside it becomes a looping flipbook
at `--flipbook-fps`, default 5). Corner normals (`vn`, Blender's default)
carry each object's hard/soft edges into the fix. A value equal
to an original's (a snapped vertex, a shared UV) is stored as a reference.
`--exclude BLOCK` (repeatable) leaves a block out of the fix; `--delete BLOCK`
(repeatable) removes every triangle of a shape whose object was deleted."""
import argparse
import json
import math
import posixpath
import sys
from pathlib import Path

from engine import mods, paths
from tools.gen_mesh_fixes import fnv1a64_hex
from tools.shape_diff import ShapeDiffError, match, obj_io, payload, smoothing as _smoothing
from tools.shape_diff import verify as _verify

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


def _texture_entry(e: dict) -> dict:
    t = {"block": e["block"], "albedo": e["albedo"]}
    if e.get("flipbook"):
        t["flipbook"] = e["flipbook"]
    return t


def make_fix_dict(rel: str, edits: list, smoothing: str = None) -> dict:
    """`smoothing`: the BSM1 payload (base64) of the authored edges, if any."""
    geometry = [e for e in edits if _has_geometry(e)]
    textures = sorted((_texture_entry(e) for e in edits if e.get("albedo")),
                      key=lambda t: t["block"])
    fix = {"format": 1, "source": rel, "generator": GENERATOR}
    if geometry or not (textures or smoothing):
        fix["shape_edits"] = payload.encode_b64(geometry)
    if textures:
        fix["textures"] = textures
    if smoothing:
        fix["smoothing"] = smoothing
    return fix


def _by_ref(positions) -> str:
    """Positions that ARE an original (snapped), not an original plus a delta."""
    n = sum(1 for p in positions if isinstance(p, payload.Ref) and p.delta is None)
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
        fb = e.get("flipbook")
        flip = (f" (flipbook {len(fb['frames'])} frames @ {fb['fps']:g} fps)" if fb else "")
        parts.append(f"texture -> {e['albedo']}{flip}")
    return f"block {e['block']}: " + ", ".join(parts)


def _smoothing_summary(fix: dict):
    if not fix.get("smoothing"):
        return None
    recs = payload.decode_smoothing_b64(fix["smoothing"])
    return (f"smoothing: {len(recs)} shapes, {sum(len(r['hard']) for r in recs)} hard / "
            f"{sum(len(r['soft']) for r in recs)} soft edges")


def fix_text(fix: dict) -> str:
    return json.dumps(fix, indent=2) + "\n"


def _verify_smoothing(rel, fix, edits, recs, names, partial):
    """Check the loader shades `recs` as Blender does. With `partial`, a
    block it shades differently loses its record (printed under "smoothing
    skipped:") and the rest are re-encoded and re-verified. Returns (fix,
    edges verified)."""
    rows = _verify.smoothing_report(_nif_path(rel), fix_text(fix))
    failures = _verify.smoothing_failures(recs, rows)
    if not (partial and failures):
        return fix, _verify.check_smoothing(recs, rows, names)
    print("smoothing skipped:")
    for block, reasons in failures.items():
        print(f"  {names[block]} (block {block}): {len(reasons)} failing edge"
              f"{'s' if len(reasons) != 1 else ''}; first: {reasons[0]}")
    recs = [r for r in recs if r["block"] not in failures]
    if not recs:
        return make_fix_dict(rel, edits), 0
    fix = make_fix_dict(rel, edits, payload.encode_smoothing_b64(recs))
    return fix, _verify.run_smoothing(_nif_path(rel), fix_text(fix), recs, names)


def build_fix(rel: str, base_path: Path, edit_path: Path, partial: bool = False,
              exclude=(), verify: bool = True, flipbook_fps: float = 5.0, delete=(),
              smoothing=None):
    """Diff, then (unless verify=False -- unit tests only) apply the fix with
    the loader and check it reproduces edit.obj and leaves every other block
    stock (spec §5.4); a mismatch raises, so nothing unverified is written.
    `smoothing` (None: same as `verify`): record the hard/soft edges of every
    edit object exported with normals, against the shapes the geometry fix
    builds, and (when verifying) check the loader shades them that way.
    Skipped, excluded and deleted blocks never get a record. A block the
    loader shades differently raises, naming every such block and edge;
    with `partial` its record is dropped instead and listed under
    "smoothing skipped:", and the rest re-verified.
    `exclude`: block numbers left out of the fix entirely (as if unedited).
    `flipbook_fps`: playback rate of every numbered frame run (spec §5.3).
    `delete`: block numbers whose objects were deleted in Blender -- every
    triangle of the shape is removed (match.with_deletions)."""
    if not (math.isfinite(flipbook_fps) and flipbook_fps > 0):
        raise ShapeDiffError(f"flipbook fps must be finite and > 0, got {flipbook_fps}")
    base_objs = obj_io.read_objects(base_path)
    edit_objs = match.with_deletions(base_objs, obj_io.read_objects(edit_path), delete)
    dirs = _texture_dirs(rel)
    shapes = _shapes(rel)
    result = match.diff(shapes, base_objs, edit_objs, partial=partial,
                        texture_dirs=dirs, exclude=exclude, flipbook_fps=flipbook_fps)
    edits, skipped = result if partial else (result, [])
    fix = make_fix_dict(rel, edits)
    recs = []
    if smoothing is None:
        smoothing = verify
    names = {obj_io.block_of(n): n for n in edit_objs}
    if smoothing:
        left_out = set(exclude) | set(delete) | {obj_io.block_of(n) for n, _ in skipped}
        authored = {b: edit_objs[n] for b, n in names.items() if b not in left_out
                    and _smoothing.edge_flags(edit_objs[n]) is not None}
        if authored:
            recs = _smoothing.records(_verify.apply(_nif_path(rel), fix_text(fix)), authored)
        if recs:
            fix = make_fix_dict(rel, edits, payload.encode_smoothing_b64(recs))
    if verify:
        edited = {e["block"]: (names[e["block"]], edit_objs[names[e["block"]]]) for e in edits}
        albedos = {e["block"]: e["albedo"] for e in edits if e.get("albedo")}
        added = {e["block"]: len(e.get("add_triangles", ())) for e in edits}
        n = _verify.run(_nif_path(rel), fix_text(fix), shapes, edited, albedos, added)
        print(f"verified {n} objects")
        if recs:
            fix, n = _verify_smoothing(rel, fix, edits, recs, names, partial)
            print(f"verified smoothing on {n} edges")
    for e in edits:
        pairs = e.get("moved_survivors")
        if pairs:
            print(f"warning: block {e['block']}: {len(pairs)} survivor(s) paired with no "
                  "position agreement (edit -> base OBJ vertex): "
                  + ", ".join(f"{a}->{b}" for a, b in pairs))
    if partial:
        return fix, edits, skipped
    return fix, edits


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
    df.add_argument("--exclude", type=int, action="append", default=[], metavar="BLOCK",
                    help="leave this block out of the fix (repeatable)")
    df.add_argument("--delete", type=int, action="append", default=[], metavar="BLOCK",
                    help="remove this block's shape entirely (its object was deleted; repeatable)")
    df.add_argument("--flipbook-fps", type=float, default=None, metavar="FPS",
                    help="playback rate of a numbered frame run <stem>_0..N-1 (default 5)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            print(export(a.nif, a.out))
            return 0
        kw = {"exclude": a.exclude} if a.exclude else {}
        if a.delete:
            kw["delete"] = a.delete
        if a.flipbook_fps is not None:
            kw["flipbook_fps"] = a.flipbook_fps
        if a.partial:
            fix, edits, skipped = build_fix(a.nif, a.base, a.edit, partial=True, **kw)
        else:
            fix, edits = build_fix(a.nif, a.base, a.edit, **kw)
            skipped = []
        for e in edits:
            print(_summary(e))
        if a.exclude:
            print("excluded: blocks " + ", ".join(str(b) for b in a.exclude))
        if a.delete:
            print("deleted: blocks " + ", ".join(str(b) for b in a.delete))
        if skipped:
            print("skipped (not yet supported):")
            for name, reason in skipped:
                print(f"  {name}: {reason}")
        smoothing = _smoothing_summary(fix)
        if smoothing:
            print(smoothing)
        if not edits and not smoothing:
            print("no changes")
            return 0
        target = _fix_dir() / (fnv1a64_hex(_nif_path(a.nif).read_bytes()) + ".json")
        if target.exists() and json.loads(target.read_text(encoding="utf-8")).get("generator") != GENERATOR:
            raise ShapeDiffError(f"{target.name} is owned by another generator; refusing to overwrite")
        if a.write:
            target.write_text(fix_text(fix), encoding="utf-8", newline="\n")
            print(f"wrote {target}")
        else:
            print(f"dry run; --write to write {target}")
        return 0
    except ShapeDiffError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
