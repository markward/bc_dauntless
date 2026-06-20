"""Phase-1 backdrop objects: StarSphere + BackdropSphere.

BC scripts call:
    kThis = App.StarSphere_Create()           # opaque starfield
    kThis = App.BackdropSphere_Create()       # alpha-blended overlay

    kThis.SetName(name)
    kThis.SetTranslateXYZ(0, 0, 0)            # always origin; ignored
    kThis.AlignToVectors(forward, up)         # world orientation
    kThis.SetTextureFileName("data/stars.tga")
    kThis.SetTargetPolyCount(256)
    kThis.SetHorizontalSpan(1.0)
    kThis.SetVerticalSpan(1.0)
    kThis.SetSphereRadius(300.0)
    kThis.SetTextureHTile(22.0)
    kThis.SetTextureVTile(11.0)
    kThis.Rebuild()                           # no-op; we evaluate at submit
    pSet.AddBackdropToSet(kThis, name)        # append-order = draw-order
    kThis.Update(0)

The renderer reads stored config via aggregate_for_renderer at the end
of this module and passes a flat list to the C++ side each tick.
"""
import json as _json
import zlib as _zlib
from functools import lru_cache as _lru_cache
from pathlib import Path as _P

from engine.appc.objects import ObjectClass

_APPEARANCE_PATH = _P(__file__).with_name("backdrop_appearance.json")


@_lru_cache(maxsize=1)
def _appearance_table():
    try:
        return _json.loads(_APPEARANCE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _proc_kind(basename):
    b = basename.lower()
    if b.startswith("stars"):
        return "stars"
    if b.startswith("galaxy"):
        return "starcloud"
    return "nebula"


def _display_tint(rgb, target=205):
    m = max(rgb) or 1
    f = target / m
    return [min(255, round(c * f)) / 255.0 for c in rgb]


def _proc_fields(basename):
    """proc_kind, colour (0..1), coverage, seed for one backdrop texture."""
    kind = _proc_kind(basename)
    row = _appearance_table().get(basename)
    mean = row["meanColor"] if row else [90, 90, 110]
    coverage = row["coverage"] if row else 0.4
    # nebula -> vivid; starcloud dust -> keep dim; stars -> unused
    color = _display_tint(mean) if kind == "nebula" else [c / 255.0 for c in mean]
    seed = (_zlib.crc32(basename.encode("utf-8")) % 100000) / 1000.0  # stable per texture, deterministic across runs
    return {"proc_kind": kind, "color": color, "coverage": coverage, "seed": seed}


class Backdrop(ObjectClass):
    """Common storage. Subclasses differ only in their `kind`
    discriminator; the rendering blend mode is selected from kind.

    Inherits ObjectClass so SetTranslateXYZ / AlignToVectors /
    GetWorldRotation come for free, matching how Light / LightPlacement
    inherit from ObjectClass.
    """
    KIND_STAR = "star"
    KIND_BACKDROP = "backdrop"

    def __init__(self, kind):
        super().__init__()
        self._kind = kind
        self._texture_path: str = ""
        self._target_poly_count: int = 256
        self._horizontal_span: float = 1.0
        self._vertical_span: float = 1.0
        self._sphere_radius: float = 300.0
        self._texture_h_tile: float = 1.0
        self._texture_v_tile: float = 1.0

    def SetTextureFileName(self, path):  self._texture_path = str(path)
    def SetTargetPolyCount(self, n):     self._target_poly_count = int(n)
    def SetHorizontalSpan(self, h):      self._horizontal_span = float(h)
    def SetVerticalSpan(self, v):        self._vertical_span = float(v)
    def SetSphereRadius(self, r):        self._sphere_radius = float(r)
    def SetTextureHTile(self, h):        self._texture_h_tile = float(h)
    def SetTextureVTile(self, v):        self._texture_v_tile = float(v)

    def Rebuild(self):
        # In real BC this regenerates the sphere mesh with the configured
        # poly count and UV mapping. We defer all geometry to the
        # renderer (cached & shared per-poly_count across all backdrops),
        # so this is a no-op. Listed explicitly rather than caught by
        # ObjectClass.__getattr__ so the name shows up in code search.
        return None


class StarSphere(Backdrop):
    def __init__(self):
        super().__init__(Backdrop.KIND_STAR)


class BackdropSphere(Backdrop):
    def __init__(self):
        super().__init__(Backdrop.KIND_BACKDROP)


def StarSphere_Create() -> StarSphere:
    return StarSphere()


def BackdropSphere_Create() -> BackdropSphere:
    return BackdropSphere()


def aggregate_for_renderer(pSet, project_root):
    """Project SetClass._backdrops into a flat list of dicts that the
    C++ side can consume verbatim.

    Each entry has shape:
        {
            "texture_path": str (absolute),
            "kind": "star" | "backdrop",
            "h_tile": float,   "v_tile": float,
            "h_span": float,   "v_span": float,
            "world_rotation": list[9] column-major flatten of the BC mat3
                              (so the C++ glm::mat3 constructor reads each
                              BC column as a GL column directly),
            "target_poly_count": int (>= 64),
            "proc_kind": "stars" | "starcloud" | "nebula" — procedural render kind,
                         classified by texture basename,
            "color": [r, g, b] floats 0..1 — recorded dominant colour
                     (nebula = brightened, starcloud = raw dim mean),
            "coverage": float 0..1 — density from the appearance table,
            "seed": float — stable per-texture seed (deterministic crc32),
        }

    Backdrops with empty texture paths are dropped silently (script
    bug we can't fix from here). Backdrops whose texture file does not
    exist under project_root/game/ are dropped with a once-per-set
    warning (pSet._backdrop_warned flag) — same gate pattern as the
    lighting overflow warning.
    """
    if pSet is None or not getattr(pSet, "_backdrops", None):
        return []

    out = []
    missing_paths = []
    for b in pSet._backdrops:
        if not b._texture_path:
            continue  # silent: script-author bug
        abs_path = (project_root / "game" / b._texture_path).resolve()
        if not abs_path.is_file():
            # BC scripts reference textures by base path (e.g.
            # "data/Backgrounds/treknebula.tga"); the actual files live
            # under <dir>/High/, <dir>/Medium/, <dir>/Low/. Try High first
            # for the highest fidelity.
            from pathlib import Path as _Path
            rel = _Path(b._texture_path)
            for lod in ("High", "Medium", "Low"):
                lod_path = (project_root / "game" /
                            rel.parent / lod / rel.name).resolve()
                if lod_path.is_file():
                    abs_path = lod_path
                    break
            else:
                missing_paths.append(b._texture_path)
                # Note: the procedural path also inherits this gate — a backdrop still needs its TGA present on disk (resolved above), even though the procedural renderer never decodes its pixels.
                continue
        rot = b.GetWorldRotation()
        # Column-major flatten. The C++ side reads m9 into glm::mat3(...)
        # which is column-major, and our BC matrix is column-vector (see
        # CLAUDE.md ↦ "Rotation matrix convention"), so m9[j*3 + i] =
        # rot._m[i][j] sends BC column j as GL column j.
        m9 = [
            rot._m[0][0], rot._m[1][0], rot._m[2][0],  # col 0 (right)
            rot._m[0][1], rot._m[1][1], rot._m[2][1],  # col 1 (forward)
            rot._m[0][2], rot._m[1][2], rot._m[2][2],  # col 2 (up)
        ]
        entry = {
            "texture_path": str(abs_path),
            "kind": b._kind,
            "h_tile": b._texture_h_tile,
            "v_tile": b._texture_v_tile,
            "h_span": b._horizontal_span,
            "v_span": b._vertical_span,
            "world_rotation": m9,
            "target_poly_count": max(int(b._target_poly_count), 64),
        }
        entry.update(_proc_fields(_P(b._texture_path).name))
        out.append(entry)

    if missing_paths and not getattr(pSet, "_backdrop_warned", False):
        print(f"[backdrops] dropped {len(missing_paths)} backdrop(s) "
              f"with unresolvable textures from set "
              f"{pSet.GetName()!r}: {missing_paths!r}", flush=True)
        pSet._backdrop_warned = True

    return out
