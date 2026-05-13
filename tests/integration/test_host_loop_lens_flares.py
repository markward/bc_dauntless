"""host_loop._aggregate_lens_flares pulls built flares from g_kSetManager
and shapes them for the renderer binding."""
from pathlib import Path
import App
from engine.host_loop import _aggregate_lens_flares
from engine.appc.sets import SetClass
from engine.appc.planet import Sun


def test_aggregate_lens_flares_pulls_from_active_sets():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    sun = Sun(radius=4040.0, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation((1.0, 2.0, 3.0))
    pSet.AddObjectToSet(sun, "Sun")
    pLens = App.LensFlare_Create(pSet)
    pLens.SetSource(sun, 6)
    pLens.AddFlare(8, "data/textures/rays.tga", 0.0, 0.2)
    pLens.Build()
    App.g_kSetManager._sets["Tau Ceti"] = pSet

    out = _aggregate_lens_flares()
    assert len(out) == 1
    f = out[0]
    # ASTRO_SCALE may be applied; assert structure rather than exact numbers.
    assert isinstance(f["source_world_pos"], tuple)
    assert len(f["source_world_pos"]) == 3
    assert len(f["elements"]) == 1
    assert Path(f["elements"][0]["texture_path"]).is_absolute()
