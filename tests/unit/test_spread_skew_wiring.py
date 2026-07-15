"""Torpedo spread selector -> skew-fire wire (2026-07-15 decomp update).

New decomp-project evidence (confirmed against the official BC SDK Model
Property Editor doc, modelpropertyeditor.html:255): BC's torpedo "spread"
selector and skew fire were ONE feature that shipped disconnected. The
intended hook -- a vtable-only salvo setter (0x0057B1F0) -- has zero callers
in retail. Dauntless wires the INTENDED behaviour: selecting a non-Single
firing chain arms skew fire on every child tube (a true simultaneous fanned
salvo, geometry from each tube's authored Right vector); selecting Single (or
clamping back to it) disarms skew fire, restoring BC's shipped 0.5 s
ship-wide walk-out.

See ``TorpedoSystem.SetFiringChainMode`` (engine/appc/weapon_subsystems.py)
for the wire itself.
"""
from unittest.mock import patch

from engine.appc.math import TGPoint3
from engine.appc.properties import TorpedoTubeProperty
from engine.appc import projectiles

from tests.helpers.torpedo_fixtures import (
    make_ship_with_torpedo_chains,
    system_with_tubes,
)


SKEW = 0.033   # audited .rdata constant, fixed sign, local frame


def test_non_single_chain_sets_skew_single_clears_it():
    ship = make_ship_with_torpedo_chains("0;Single;123;Dual;53;Quad")
    torps = ship.GetTorpedoSystem()
    tubes = [torps.GetWeapon(i) for i in range(torps.GetNumWeapons())]
    assert all(t.IsSkewFire() == 0 for t in tubes), "fresh tubes start skew-off"

    torps.SetFiringChainMode(1)          # "Dual" -> [1, 2, 3] != [0]
    assert all(t.IsSkewFire() == 1 for t in tubes)

    torps.SetFiringChainMode(0)          # "Single" -> [0]
    assert all(t.IsSkewFire() == 0 for t in tubes)

    torps.SetFiringChainMode(2)          # "Quad" -> [5, 3] != [0]
    assert all(t.IsSkewFire() == 1 for t in tubes)

    torps.SetFiringChainMode(-1)         # clamps back to Single (0)
    assert torps.GetFiringChainMode() == 0
    assert all(t.IsSkewFire() == 0 for t in tubes), "clamping back to Single must clear skew"


def test_chainless_ship_leaves_tubes_skew_off():
    ship = make_ship_with_torpedo_chains("")
    torps = ship.GetTorpedoSystem()
    tubes = [torps.GetWeapon(i) for i in range(torps.GetNumWeapons())]

    torps.SetFiringChainMode(5)          # any n; chainless clamps to hi=0
    assert torps.GetFiringChainMode() == 0
    assert all(t.IsSkewFire() == 0 for t in tubes), (
        "a chainless ship's fallback chain is [0] ('all weapons', single-fire) "
        "-- SetFiringChainMode must never arm skew on it"
    )


def _galaxy_forward_rights():
    """galaxy.py ForwardTorpedo1-4's authored Right vectors -- a 4-way
    fan cross on +/-X and +/-Z."""
    return [
        TGPoint3(-1.0, 0.0, 0.0),
        TGPoint3(0.0, 0.0, -1.0),
        TGPoint3(1.0, 0.0, 0.0),
        TGPoint3(0.0, 0.0, 1.0),
    ]


def _expected_fan_direction(right):
    d = TGPoint3(SKEW * right.x, 1.0, SKEW * right.z)
    length = d.Length()
    return TGPoint3(d.x / length, d.y / length, d.z / length)


def _same_dir(a, b, tol=1e-6):
    return (abs(a.x - b.x) < tol and abs(a.y - b.y) < tol and abs(a.z - b.z) < tol)


def test_quad_chain_fires_simultaneous_fanned_salvo():
    """Galaxy-style 4-tube system: selecting the Quad chain (groups [5, 3],
    group 5 = all four forward tubes) fires ALL of them in the SAME tick
    (skew exempts each from the 0.5s ship-wide stagger), fanned symmetrically
    about tube-forward by the authored Right cross."""
    system, ship = system_with_tubes(4)
    masks = [25, 25, 26, 26]             # galaxy.py ForwardTorpedo1-4.SetGroups
    rights = _galaxy_forward_rights()
    for i in range(4):
        tube = system.GetWeapon(i)
        prop = TorpedoTubeProperty("FT%d" % i)
        prop.SetGroups(masks[i])
        # SetProperty mirrors Direction/Right off the property (subsystems.py)
        # -- set it BEFORE the explicit SetDirection/SetRight below, or those
        # explicit calls get clobbered back to the property's defaults.
        tube.SetProperty(prop)
        tube.SetDirection(TGPoint3(0.0, 1.0, 0.0))
        tube.SetRight(rights[i])
        assert tube.IsMemberOfGroup(5) == 1   # sanity: all four are group-5 members

    system.GetProperty().SetFiringChainString("0;Single;123;Dual;53;Quad")
    system.SetFiringChainMode(2)         # "Quad" -> [5, 3]
    assert all(system.GetWeapon(i).IsSkewFire() == 1 for i in range(4))

    before = len(projectiles._active)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(None, None)   # one tap

    assert all(system.GetWeapon(i).GetNumReady() == 0 for i in range(4)), (
        "stagger bypassed by skew -- all 4 tubes must launch in the same tick"
    )

    launched = projectiles._active[before:]
    assert len(launched) == 4

    actual_dirs = []
    for torp in launched:
        v = torp._velocity
        speed = v.Length()
        actual_dirs.append(TGPoint3(v.x / speed, v.y / speed, v.z / speed))

    expected = [_expected_fan_direction(r) for r in rights]
    remaining = list(actual_dirs)
    for exp in expected:
        match = next((a for a in remaining if _same_dir(a, exp)), None)
        assert match is not None, (
            f"no launched torpedo matches expected fan direction {exp!r}; "
            f"got {actual_dirs!r}"
        )
        remaining.remove(match)

    # Pairwise distinct headings (the fan, not a clump).
    for i in range(len(actual_dirs)):
        for j in range(i + 1, len(actual_dirs)):
            assert not _same_dir(actual_dirs[i], actual_dirs[j], tol=1e-9), (
                "fanned salvo produced two identical headings"
            )
