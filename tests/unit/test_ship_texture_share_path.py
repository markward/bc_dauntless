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
from tests.helpers.bc_assets import require_game_dir


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
    require_game_dir("data/Models/Ships")
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


def test_nif_own_directory_is_in_the_texture_search():
    """The NIF's OWN directory must be searched, not only <NIFdir>/<tier>.

    Community ship mods have kept their textures loose beside the .NIF for
    twenty years and stbc.exe loads them, so the bare directory is a real
    search location and not a leniency for malformed content. Our loader
    composed only ``<NIFdir>/<tier>``, so every such ship resolved nothing:
    model_build caught the TextureNotFound, substituted its magenta
    checkerboard, and the hull rendered as a blown-out magenta silhouette.

    Ordering matters and is asserted here: ``<NIFdir>/<tier>`` must still come
    FIRST so a properly tiered ship keeps honouring the detail setting, and
    the bare directory must come BEFORE the shared dirs so a ship's own
    texture wins over a same-named file in SharedTextures.
    """
    require_game_dir("data/Models/Ships")
    from engine import host_loop as hl

    App.g_kLODModelManager.Purge()

    sess = hl.MissionSession(mission_name="t")
    r = _CaptureRenderer()
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, "S")
    ship = App.ShipClass_Create()
    ship.SetName("Galaxy-1")
    ship.SetScript("Galaxy")
    s.AddObjectToSet(ship, "Galaxy-1")

    hl.realize_set_objects(sess, s, r)

    assert r.searches, "Galaxy was never handed to load_model"
    search = _norm(r.searches[0])

    model_dir = next((d for d in search
                      if d.endswith("data/Models/Ships/Galaxy")), None)
    assert model_dir is not None, (
        "the NIF's own directory is absent from the texture search list; "
        "a mod keeping its textures beside the .NIF cannot resolve them.\n"
        "search list was:\n  " + "\n  ".join(search))

    tier_dir = next((d for d in search
                     if d.endswith("data/Models/Ships/Galaxy/High")), None)
    assert tier_dir is not None, "the tiered dir vanished"
    assert search.index(tier_dir) < search.index(model_dir), (
        "<NIFdir>/<tier> must precede the bare <NIFdir> so a tiered ship "
        "still honours the texture-detail setting")

    shared = next((i for i, d in enumerate(search)
                   if "SharedTextures" in d), None)
    if shared is not None:
        assert search.index(model_dir) < shared, (
            "the ship's own directory must precede SharedTextures so its own "
            "texture wins over a same-named shared one")
