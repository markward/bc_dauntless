"""g_kTextureAnimManager records frame rects and infers regular grids
(spec 2026-10-16 §7.5)."""
import App
from engine.appc import particles as P
from engine.appc import texture_anim


def _declare(path, cols, rows):
    track = App.g_kTextureAnimManager.AddContainer(path).AddTextureTrack(cols * rows)
    i = 0
    for r in range(rows):
        for c in range(cols):
            x, y = c / cols, r / rows
            track.SetFrame(i, x, y + 1.0 / rows, x + 1.0 / cols, y)
            i += 1


def test_regular_grid_is_inferred_and_used_by_create_target():
    _declare("scripts/Custom/MyMod/Gfx/Boom.tga", 8, 4)
    assert texture_anim.grid_for("scripts\\custom\\mymod\\gfx\\BOOM.tga") == (8, 4)
    c = P.AnimTSParticleController_Create()
    c.CreateTarget("scripts/Custom/MyMod/Gfx/Boom.tga")
    assert (c._atlas_cols, c._atlas_rows) == (8, 4)


def test_irregular_track_is_ignored():
    track = App.g_kTextureAnimManager.AddContainer("x/odd.tga").AddTextureTrack(2)
    track.SetFrame(0, 0.0, 0.5, 0.5, 0.0)
    track.SetFrame(1, 0.5, 0.3, 1.0, 0.0)
    assert texture_anim.grid_for("x/odd.tga") is None
