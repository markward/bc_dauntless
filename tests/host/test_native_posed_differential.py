"""Posed ships run natively and bit-identically to the Python in a fight
with REAL render instances (native combat posed parts, Task 5; spec
docs/superpowers/specs/2026-11-01-native-combat-posed-parts-design.md §5).

The headless twin (tests/integration/test_native_posed_differential.py) has
no instances. This one boots the headless host (a real `g_world`), loads
combat_stress plus the second Bird of Prey and realizes every ship through
host_loop's own `realize_set_objects`, as the K2/K3 host differentials do:
radii and shield hull boxes from the models, the Bird of Prey's per-part
boxes DERIVED from its model and its leaf model learned (so a mount is
attributed by `model_nearest_part`, not the box rule), K2 and K3 tracing the
real hull meshes, and a severed wing handed to the renderer with the real
instance id.

Review Focus 1 in the fight: the Bird of Prey's leaf model is forgotten
before it (every slot then resolves by the box rule) and learned again at
MODEL_AT, before the first shot -- the model-learned trigger bumps the
part-map generation, every slot reads stale until the next step boundary
re-resolves it by the model, and the arms stay equal from there.

RENDER SYNC as the K2/K3 host files: at the top of each frame every realized
ship's instance is set to host_loop's `_ship_world_matrix`.

Everything the headless file asserts holds here too (posed_fight's record,
compared per tick; no posed hand-back; every posed branch run natively),
plus the real-instance branches: the mesh tier and the shield bubble.

The forced-part Galaxy (Friend-3: banks on "probe part" / "probe flat",
one identity only within `is_identity`'s 1e-9, its Phasers system sharing
a bank's point) is COVERED BY THE HEADLESS FILE, not this one: here the
Galaxy's boxes are derived from its real model, which has no such parts,
so `physical_parents` falls back to Auto and its banks ride no forced
part. The setup's assertions still pass here; the posed-bank and R3
coverage this file reports comes from the Birds of Prey.

Picked spots (fire control native only, M5): a torpedo at a spot no mount
claims steers at it as a plain body point natively -- check_posed asserts
no posed steer ASK.
"""
import os
import time

import pytest

import App
from tests.helpers import bc_assets

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_set_part_slot"),
    reason="native posed-parts bindings not built")

from engine.appc import articulation  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import part_severance  # noqa: E402
from engine.appc import subsystems as ss  # noqa: E402
from tests.helpers.posed_fight import (CRUISE_BOP, LEAF, both,  # noqa: E402
                                       check_posed, report)

BOP_NIF = (bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "BirdOfPrey"
           / "BirdOfPrey.nif")

SEED = 20261106
MODEL_AT = 30


@pytest.fixture(scope="module")
def host():
    """The headless host (a real g_world), booted once for the module."""
    if not BOP_NIF.is_file():
        pytest.skip("BC assets not available")
    from engine import renderer as r
    saved = os.environ.get("OPEN_STBC_HOST_HEADLESS")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        try:
            r.init(256, 256, "native-posed-differential")
        except RuntimeError as e:
            pytest.skip(f"no GL context: {e}")
        try:
            yield r
        finally:
            r.shutdown()
    finally:
        if saved is None:
            os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
        else:
            os.environ["OPEN_STBC_HOST_HEADLESS"] = saved


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))
    nc.reset()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    if _h.combat_k2_open():
        _h.combat_k2_abandon()
    nc.reset()


def _hexes(p):
    return (p.x.hex(), p.y.hex(), p.z.hex())


def forget_model(scene, mp):
    """Before the fight: the Bird of Prey's leaf model (and the mount answers
    cached from it) forgotten, through `mp` (back when the arm closes), so
    every slot first resolves by the box rule."""
    assert articulation.leaf_model(LEAF), "realize did not learn the model"
    mp.delitem(articulation._leaf_models, LEAF)
    for key in [k for k in part_severance._mount_parts if k[0] == LEAF]:
        mp.delitem(part_severance._mount_parts, key)
    scene.stats["model_moved"] = 0
    scene.stats["model_hits_before"] = 0


def learn_model(scene):
    """At MODEL_AT, before any shot: the model learned again (the trigger
    realize uses: `part_boxes_for` with a real instance id). Every slot
    reads stale (checked natively), and mounts the model attributes
    differently from the box rule move."""
    if scene.tick != MODEL_AT:
        return
    import App as _App
    scene.stats["model_hits_before"] = sum(
        1 for e in scene.rec.events if e[0] == _App.ET_WEAPON_HIT)
    assert not articulation.leaf_model(LEAF)
    bop = scene.by_name[CRUISE_BOP]
    before = [_hexes(ss._subsystem_world_position(s, a))
              for s, a in scene.mount_subs(bop)]
    articulation.part_boxes_for(LEAF, scene.iid(bop))
    assert articulation.leaf_model(LEAF)
    after = [_hexes(ss._subsystem_world_position(s, a))
             for s, a in scene.mount_subs(bop)]
    scene.stats["model_moved"] = sum(1 for x, y in zip(before, after)
                                     if x != y)
    scene.check_stale()


@pytest.mark.parametrize("ticks_per_frame", (1, 4))
def test_posed_fight_matches_python_with_real_instances(
        monkeypatch, host, ticks_per_frame):
    t0 = time.perf_counter()
    ref, nat = both(monkeypatch, ticks_per_frame, SEED, r=host,
                    setup=forget_model, before_tick=learn_model)
    report("posed host differential", ticks_per_frame,
           time.perf_counter() - t0, ref, nat)
    check_posed(ref, nat)
    # Review Focus 1: the model was learned before any hit, the bump made
    # the slots stale (stale_seen counts it with the generation beats), and
    # no kernel read a slot resolved before it (posed fallbacks 0, above).
    assert nat.stats["model_hits_before"] == 0, nat.stats
    # ... and it changed the answer: mounts the model gives another part
    # than the box rule did moved (both arms alike: check_posed).
    assert nat.stats["model_moved"] > 0, nat.stats
    # An offline phaser system whose banks are all idle was stopped with
    # logged writes (round trips Task 3; measured 135 at tpf 1, 46 at 4).
    assert nat.counts["k2_logged_system_stop"] > 0, nat.counts
    # The real-instance branches, in the kernel.
    n = nat.rec.tally.n
    for key in ("tier:mesh", "bubble", "normal", "steer_point:posed"):
        assert n.get(key, 0) > 0, (key, n)
    hits = [e for e in ref.rec.events if e[0] == App.ET_WEAPON_HIT]
    assert hits and all(e[4] is not None for e in hits)
