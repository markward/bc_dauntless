"""Regression: non-Federation ships must have their SetTextureSharePath
directory in the texture search list handed to load_model.

BC's original texture-directory composer (FUN_0044f4a0 @ 0x0044f4a0) builds
the search set from (a) the NIF's own dir and (b) the SetTextureSharePath
override (default ``data/Models/SharedTextures``), each suffixed by the
graphics texture-detail tier (Low/Medium/High). Our loader had hardcoded
only the Federation dirs, so every non-Fed hull (Cardassian ``CardShips``,
Klingon ``KlingShips``, …) failed its *primary* texture resolve in the native
model builder — an unguarded ``resolve()`` that throws ``TextureNotFound`` —
and the whole ship was silently skipped: invisible model, GetRadius()==0,
targeting reticle collapsed to a point.

The Galor/Keldon NIFs reference ``CardGalor01_glow.tga``, which lives ONLY in
``data/Models/SharedTextures/CardShips/High``.
"""

import App
from engine.appc.sets import SetClass_Create


class _CaptureRenderer:
    """Fake renderer that records the texture search list per load_model."""

    def __init__(self):
        self._next = 1
        self.searches = []

    def load_model(self, path, search, texture_replacements=None):
        self.searches.append(list(search))
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        return iid

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_rim_strength(self, iid, s):
        pass


def _norm(paths):
    return [p.replace("\\", "/") for p in paths]


def test_cardassian_share_path_reaches_texture_search():
    from engine import host_loop as hl

    # Reproduce the LIVE cold path: our engine loads NIFs itself and never calls
    # the SDK ship script's LoadModel(), so the LODModel (which records
    # SetTextureSharePath) is NOT pre-registered. The loader must self-register
    # it to recover the CardShips share path. Purge guards against another test
    # having already registered it (which would mask the bug).
    App.g_kLODModelManager.Purge()

    sess = hl.MissionSession(mission_name="t")
    r = _CaptureRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("Galor-1")
    ship.SetScript("Galor")
    s.AddObjectToSet(ship, "Galor-1")

    hl.realize_set_objects(sess, s, r)

    assert r.searches, "Galor was never handed to load_model"
    search = _norm(r.searches[0])
    assert any("data/Models/SharedTextures/CardShips/High" in d for d in search), (
        "CardShips/High missing from texture search — Cardassian textures "
        f"cannot be resolved and the ship will be skipped. Got: {search}"
    )
