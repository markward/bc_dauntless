"""Tests for engine.appc.lens_flare."""
from engine.appc.sets import SetClass
from engine.appc.lens_flare import LensFlare, LensFlare_Create


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
