"""Tests for engine.appc.lens_flare."""
from pathlib import Path
from engine.appc.sets import SetClass
from engine.appc.lens_flare import LensFlare, LensFlare_Create, aggregate_lens_flares_for_renderer
from engine.appc.planet import Sun


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_setclass_initializes_empty_lens_flares_list():
    pSet = SetClass()
    assert pSet._lens_flares == []


def test_lens_flare_create_registers_on_set():
    pSet = SetClass()
    flare = LensFlare_Create(pSet)
    assert isinstance(flare, LensFlare)
    assert pSet._lens_flares == [flare]


def test_set_source_records_object_and_direction_mode():
    flare = LensFlare(pSet=None)
    sentinel = object()
    flare.SetSource(sentinel, 6)
    assert flare._source is sentinel
    assert flare._direction_mode == 6


def test_add_flare_accumulates_elements_with_defaults():
    flare = LensFlare(pSet=None)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3, 0.5, 0.1)
    flare.AddFlare(30, "data/textures/whiteloop.tga", 0.0, 0.075)
    assert flare._elements == [
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3, "freq": 0.5, "amp": 0.1},
        {"wedges": 30, "texture": "data/textures/whiteloop.tga",
         "position": 0.0, "size": 0.075, "freq": 0.0, "amp": 0.0},
    ]


def test_build_marks_flare_as_built():
    flare = LensFlare(pSet=None)
    assert flare._built is False
    flare.Build()
    assert flare._built is True


def test_lens_flare_create_returns_early_when_pset_lacks_attr():
    """Defensive: a SetClass that somehow predates this feature (or a None
    pSet from a malformed mission script) shouldn't crash."""
    flare = LensFlare_Create(None)
    assert isinstance(flare, LensFlare)
    assert flare._set is None


# ── Task 3: aggregate_lens_flares_for_renderer ───────────────────────────────


def _make_set_with_built_flare(elements):
    pSet = SetClass()
    sun = Sun(radius=4000.0, model_path="data/Textures/SunBase.tga")
    sun.SetWorldLocation((10.0, 20.0, 30.0))
    pSet.AddObjectToSet(sun, "Sun")
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    for e in elements:
        flare.AddFlare(**e)
    flare.Build()
    return pSet, sun, flare


def test_aggregator_returns_descriptor_for_built_flare():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3},
        {"wedges": 30, "texture": "data/textures/whiteloop.tga",
         "position": 1.4, "size": 0.075},
    ])

    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])

    assert len(out) == 1
    d = out[0]
    assert d["source_world_pos"] == (10.0, 20.0, 30.0)
    assert d["source_radius"] == 4000.0
    assert len(d["elements"]) == 2
    e0 = d["elements"][0]
    assert e0["wedges"] == 8
    assert e0["texture_path"].endswith("rays.tga")
    assert Path(e0["texture_path"]).is_absolute()
    assert e0["position"] == 0.0
    assert e0["size"] == 0.3
    assert e0["freq"] == 0.0
    assert e0["amp"] == 0.0


def test_aggregator_skips_unbuilt_flares():
    pSet = SetClass()
    sun = Sun(radius=4000.0)
    sun.SetWorldLocation((0.0, 0.0, 0.0))
    pSet.AddObjectToSet(sun, "Sun")
    flare = LensFlare_Create(pSet)
    flare.SetSource(sun, 6)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    # No Build() call.
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_skips_flares_with_no_source():
    pSet = SetClass()
    flare = LensFlare_Create(pSet)
    flare.AddFlare(8, "data/textures/rays.tga", 0.0, 0.3)
    flare.Build()
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_skips_flares_with_no_elements():
    pSet, sun, flare = _make_set_with_built_flare([])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out == []


def test_aggregator_drops_elements_whose_textures_do_not_resolve():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 8, "texture": "data/textures/rays.tga",
         "position": 0.0, "size": 0.3},
        {"wedges": 6, "texture": "data/textures/nope_does_not_exist.tga",
         "position": 0.5, "size": 0.1},
    ])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert len(out) == 1
    assert len(out[0]["elements"]) == 1
    assert out[0]["elements"][0]["texture_path"].endswith("rays.tga")


def test_aggregator_clamps_wedges_to_valid_range():
    pSet, sun, _ = _make_set_with_built_flare([
        {"wedges": 2,  "texture": "data/textures/rays.tga", "position": 0.0, "size": 0.3},
        {"wedges": 99, "texture": "data/textures/rays.tga", "position": 0.0, "size": 0.3},
    ])
    out = aggregate_lens_flares_for_renderer(PROJECT_ROOT, [pSet])
    assert out[0]["elements"][0]["wedges"] == 3   # min clamp
    assert out[0]["elements"][1]["wedges"] == 64  # max clamp
