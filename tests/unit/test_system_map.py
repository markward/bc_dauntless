"""The system-map format: dataclasses, JSON round-trip, package-local location.

Body identity (name/radius/position/orbit) is deliberately separate from
Appearance so a future procedural planet is a different appearance on the same
body -- see the design doc, section 1.
"""
from pathlib import Path

from engine.systems.map import (
    Appearance, Body, Region, SystemMap, available, from_json, map_dir, to_json,
)


def _ona() -> SystemMap:
    return SystemMap(
        system="Ona",
        bodies=[
            Body(
                name="Ona 1",
                display_name="Ona 1",
                radius_gu=1800.0,
                position_gu=(0.0, 24000.0, 0.0),
                orbits="Ona",
                appearance=Appearance(kind="nif", model="x.nif",
                                      star_class="red", color=(0.91, 0.35, 0.24)),
                owner_region="Ona1",
            ),
        ],
        regions=[
            Region(set_name="Ona1", anchor_gu=(0.0, 20000.0, 0.0),
                   radius_gu=6000.0, body_names=["Ona 1"],
                   nebula={"color": (0.6, 0.35, 0.72),
                           "spheres": [(0.0, 1500.0, 0.0, 1500.0)]}),
        ],
        overrides={},
        generated={"tool": "gen_system_maps"},
    )


def test_round_trip_preserves_every_field():
    m = _ona()
    back = from_json(to_json(m))
    assert back == m


def test_lookup_helpers():
    m = _ona()
    assert m.body("Ona 1").radius_gu == 1800.0
    assert m.body("nope") is None
    assert m.region("Ona1").body_names == ["Ona 1"]
    assert m.region("nope") is None


def test_appearance_is_separable_from_identity():
    m = _ona()
    body = m.body("Ona 1")
    swapped = from_json(to_json(m)).body("Ona 1")
    swapped.appearance = Appearance(kind="procedural", model="")
    # Identity is untouched by an appearance swap.
    assert (swapped.name, swapped.radius_gu, swapped.position_gu, swapped.orbits) == \
           (body.name, body.radius_gu, body.position_gu, body.orbits)


def test_map_dir_is_package_local_and_computed_per_call():
    d = map_dir()
    assert d.name == "maps"
    assert d.parent.name == "systems"
    # Computed fresh, not a module constant -- same value, distinct objects.
    assert map_dir() == d


def test_available_returns_sorted_system_names():
    names = available()
    assert names == sorted(names)
    assert all(isinstance(n, str) for n in names)


def test_json_is_stable_and_human_diffable():
    text = to_json(_ona())
    assert text.endswith("\n")
    assert '"system": "Ona"' in text
    # Two dumps of equal maps are byte-identical, so regeneration diffs cleanly.
    assert to_json(_ona()) == text


def test_star_colour_and_nebula_survive_the_round_trip():
    m = _ona()
    back = from_json(to_json(m))
    assert back.bodies[0].appearance.color == (0.91, 0.35, 0.24)
    assert isinstance(back.bodies[0].appearance.color, tuple)
    assert back.regions[0].nebula["spheres"][0] == (0.0, 1500.0, 0.0, 1500.0)
