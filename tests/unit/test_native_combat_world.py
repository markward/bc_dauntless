"""The world around the mirrored objects, written through to the native
combat mirror (engine/appc/native_combat.py): sets (their ordered ship and
nebula lists and their RESOLVED profile frame), MetaNebula spheres / fbm /
seed, the radial system profiles, and the scalar dials and constants
can_detect reads.

Every structure is written through its PUBLIC API and read back with
combat_dump / combat_dump_globals. Floats are compared by float.hex(): no
tolerance.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import contact_index  # noqa: E402
from engine.appc import native_combat as nc  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
ZERO = (0.0, 0.0, 0.0)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    yield
    nc.reset()


def _slot(obj):
    return obj.__dict__["_nslot"]


def _dump(obj):
    return _h.combat_dump(_slot(obj))


def _slots(objs):
    return [_slot(o) for o in objs]


def _hex(values):
    return tuple(float(v).hex() for v in values)


def _set(name=None):
    pSet = App.SetClass_Create()
    if name is not None:
        pSet.SetName(name)
    return pSet


# ── Set membership ───────────────────────────────────────────────────────────

def test_set_ship_order_matches_contact_index():
    nc.configure(ON)
    pSet = _set("world_order")
    a, b, c = (App.ShipClass_Create(n) for n in ("A", "B", "C"))
    for ship in (a, b, c):
        pSet.AddObjectToSet(ship, ship.GetName())
    assert _dump(pSet)["ships"] == _slots(contact_index.ships_in(pSet))
    assert _dump(pSet)["ships"] == _slots([a, b, c])

    pSet.RemoveObjectFromSet("A")
    assert _dump(pSet)["ships"] == _slots(contact_index.ships_in(pSet))
    pSet.AddObjectToSet(a, "A")                 # re-added: now last
    assert _dump(pSet)["ships"] == _slots(contact_index.ships_in(pSet))
    assert _dump(pSet)["ships"] == _slots([b, c, a])
    pSet.DeleteObjectFromSet("C")
    assert _dump(pSet)["ships"] == _slots(contact_index.ships_in(pSet))
    assert _dump(pSet)["ships"] == _slots([b, a])

    contact_index.forget_set(pSet)
    assert _dump(pSet)["ships"] == [] == list(contact_index.ships_in(pSet))
    pSet.AddObjectToSet(c, "C")
    assert _dump(pSet)["ships"] == _slots([c])
    contact_index.reset()
    assert _dump(pSet)["ships"] == []


def test_containing_set_is_the_set_handle():
    """Sets register at SetClass init, so an object in a set names it."""
    nc.configure(ON)
    pSet = _set("world_containing")
    ship = App.ShipClass_Create("Contained")
    pSet.AddObjectToSet(ship, "Contained")
    assert _dump(ship)["_containing_set"] == _slot(pSet)
    pSet.RemoveObjectFromSet("Contained")
    assert _dump(ship)["_containing_set"] == -1


def test_a_dropped_ship_reads_unrepresentable_in_its_set_list():
    """A ship whose row was dropped (an unencodable value) stays in the
    Python bucket: the set list keeps its place with -2, never shortens."""
    nc.configure(ON)
    pSet = _set("world_dropped")
    a, b = App.ShipClass_Create("DA"), App.ShipClass_Create("DB")
    pSet.AddObjectToSet(a, "DA")
    pSet.AddObjectToSet(b, "DB")
    a._radius = "not a float"                   # drops a's row
    assert "_nslot" not in a.__dict__
    assert _dump(pSet)["ships"] == [-2, _slot(b)]


def test_a_dropped_set_reads_unrepresentable_on_its_members():
    nc.configure(ON)
    pSet = _set("world_dropped_set")
    ship = App.ShipClass_Create("Member")
    pSet.AddObjectToSet(ship, "Member")
    nc._drop(pSet)
    assert _dump(ship)["_containing_set"] == -2


# ── Nebulae ──────────────────────────────────────────────────────────────────

def test_nebula_spheres_and_seed():
    from engine.appc.nebula import DEFAULT_FBM_DIALS
    nc.configure(ON)
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 0.6)
    row = _dump(neb)
    assert row["is_meta_nebula"] == 1
    assert row["spheres"] == []
    assert row["_seed"] is None                 # native derives it
    assert _hex(row["_fbm"]) == _hex(DEFAULT_FBM_DIALS)

    neb.AddNebulaSphere(10, 20.5, -30, 400)
    neb.AddNebulaSphere(1.25, 2, 3, 50.5)
    got = _dump(neb)["spheres"]
    assert [_hex(s) for s in got] == [_hex(s) for s in
                                      neb.GetNebulaSpheres()]
    assert _dump(neb)["_seed"] is None          # not read yet: still lazy
    seed = neb.GetSeed()                        # Python caches it
    assert _hex(_dump(neb)["_seed"]) == _hex(seed)

    neb.SetFbmDials(0.05, 1.2, 0.5)
    assert _hex(_dump(neb)["_fbm"]) == _hex((0.05, 1.2, 0.5))

    # Read before any sphere: Python caches the (0,0,0)-based seed, and the
    # cached value is pushed and wins over the first sphere added later.
    early = App.MetaNebula_Create()
    s0 = early.GetSeed()
    early.AddNebulaSphere(500, 600, 700, 10)
    assert _hex(_dump(early)["_seed"]) == _hex(s0)

    # In a set: the nebula list follows contact_index.nebulae_in.
    pSet = _set("world_nebula")
    pSet.AddObjectToSet(neb, "Neb")
    pSet.AddObjectToSet(early, "Early")
    assert _dump(pSet)["nebulae"] == _slots(contact_index.nebulae_in(pSet))
    assert _dump(pSet)["nebulae"] == _slots([neb, early])
    pSet.RemoveObjectFromSet("Neb")
    assert _dump(pSet)["nebulae"] == _slots([early])


# ── The profile frame ────────────────────────────────────────────────────────

def _python_frame(pSet):
    """What profile.locate resolves for an object in pSet."""
    from engine.systems import frames, resolve
    f = frames.frame_of(pSet)
    m = resolve.map_of(f.key[1])
    star = next(b for b in m.bodies if b.orbits is None)
    return m.profile, f.anchor_gu, tuple(star.position_gu)


def test_frame_follows_mark_mapped_and_rename():
    from engine.systems import profile, region_hooks
    nc.configure(ON)
    pSet = _set()
    row = _dump(pSet)
    assert (row["mapped"], row["profile"]) == (0, -1)
    assert row["anchor"] == ZERO and row["star"] == ZERO

    pSet.SetName("Vesuvi4")                     # named, not yet mapped
    assert (_dump(pSet)["mapped"], _dump(pSet)["profile"]) == (0, -1)

    region_hooks.mark_mapped(pSet)
    prof, anchor, star = _python_frame(pSet)
    row = _dump(pSet)
    assert row["mapped"] == 1
    assert row["profile"] >= 0
    assert _hex(row["anchor"]) == _hex(anchor)
    assert _hex(row["star"]) == _hex(star)
    prow = _h.combat_dump(row["profile"])
    assert [_hex(r) for r in prow["rows"]] == [
        _hex((r.distance_gu, r.sensors)) for r in prof.rows]
    assert float(prow["full_concealment"]).hex() == float(
        prof.full_concealment).hex()

    # One profile row per system map, shared by every set of that system.
    other = _set("Vesuvi4")
    region_hooks.mark_mapped(other)
    assert _dump(other)["profile"] == row["profile"]

    # QuickBattle renames a set in place: the name no longer resolves, so
    # Python reads the set as unmapped -- and so must the mirror.
    pSet.SetName("Vesuvi4Dupe")
    ship = App.ShipClass_Create("Renamed")
    pSet.AddObjectToSet(ship, "Renamed")
    assert profile.locate(ship) is None
    row = _dump(pSet)
    assert (row["mapped"], row["profile"]) == (0, -1)
    assert row["anchor"] == ZERO and row["star"] == ZERO


def test_set_frame_rejects_a_bad_profile_handle():
    nc.configure(ON)
    pSet = _set()
    with pytest.raises(ValueError):
        _h.combat_set_frame(_slot(pSet), _slot(pSet), ZERO, ZERO)


# ── Dials and constants ──────────────────────────────────────────────────────

_SENSOR_DIALS = ("sensorless_range_gu", "cloak_bubble_cap_gu",
                 "overboost_threshold", "min_blocker_radius_gu")
_CONSTANTS = ("CONCEAL_K", "LOCK_BREAK_T", "HYSTERESIS",
              "PROFILE_CONCEALMENT_CAP", "CLOAK_RANGE_FACTOR",
              "CLOAK_DETECTION_BASE_GU")


def _assert_globals_match_python():
    import engine.dev_mode as dev_mode
    from engine import dev_nebula_dials
    from engine.appc import sensor_detection as sd
    from engine.appc import sensor_dials
    from engine.appc import sensor_occlusion as occ
    g = _h.combat_dump_globals()
    for name in _SENSOR_DIALS:
        assert float(g[name]).hex() == sensor_dials.get(name).hex(), name
    assert float(g["conceal_cap"]).hex() == float(
        dev_nebula_dials.conceal_cap()).hex()
    assert g["dev_mode"] == int(bool(dev_mode.is_enabled()))
    assert g["occ_enabled"] == int(bool(occ.enabled()))
    assert g["enhanced_sensor_contest"] == int(bool(
        sd.ENHANCED_SENSOR_CONTEST))
    for name in _CONSTANTS:
        assert float(g[name]).hex() == float(getattr(sd, name)).hex(), name


def test_dials_push_on_step_and_reset(monkeypatch):
    from engine import dev_nebula_dials
    from engine import renderer
    from engine.appc import sensor_dials
    from engine.appc import sensor_occlusion as occ
    monkeypatch.setattr(renderer, "system_nebula_set_dials",
                        lambda d: None, raising=False)
    monkeypatch.setattr(dev_nebula_dials, "_dials",
                        dict(dev_nebula_dials.DEFAULTS))
    nc.configure(ON)
    _assert_globals_match_python()

    for name in _SENSOR_DIALS:
        before = _h.combat_dump_globals()[name]
        sensor_dials._step(name, +1)
        after = _h.combat_dump_globals()[name]
        assert after != before, name
        _assert_globals_match_python()
    sensor_dials.reset()
    _assert_globals_match_python()
    assert _h.combat_dump_globals()["sensorless_range_gu"] == 2000.0

    dev_nebula_dials._step("conceal_cap", -1)
    assert _h.combat_dump_globals()["conceal_cap"] == 0.18
    _assert_globals_match_python()

    occ.set_enabled(False)
    assert _h.combat_dump_globals()["occ_enabled"] == 0
    occ.reset_enabled()
    assert _h.combat_dump_globals()["occ_enabled"] == 1
    _assert_globals_match_python()

    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_set_globals_rejects_unknown_keys():
    with pytest.raises(ValueError):
        _h.combat_set_globals({"no_such_dial": 1.0})


# ── Resync ───────────────────────────────────────────────────────────────────

_SYSTEM_FIELDS = ("_phaser_system", "_pulse_weapon_system",
                  "_tractor_beam_system", "_torpedo_system")
_REF_FIELDS = {"_containing_set", "_sensor_subsystem", "_cloaking_subsystem",
               "_hull", "_parent_subsystem", "_parent_ship", "_property",
               "ships", "nebulae", "_target", "_held_target", "_target_list",
               "_children", "_target_subsystem", "_shield_subsystem",
               "_impulse_engine_subsystem", "mount_order",
               # The native power piece's plant and consumers (phase 6 A1).
               "_power_subsystem", "_powered_consumers",
               # ... and its repair bay, queue and notified set (Task 5).
               "_repair_subsystem", "_queue", "_cannot_complete_notified",
               *_SYSTEM_FIELDS}
_PER_PROCESS = {"obj_id", "xform_index", "xform_gen", "py_id"}


def _build_world(tag):
    """Two sets (one mapped), ships added/removed, a MetaNebula with spheres
    and a cached seed. Returns {name: object}."""
    from engine.systems import region_hooks
    mapped = _set("Belaruz1")
    region_hooks.mark_mapped(mapped)
    plain = _set("world_plain_" + tag)
    a, b, c = (App.ShipClass_Create(tag + n) for n in ("a", "b", "c"))
    for ship in (a, b, c):
        mapped.AddObjectToSet(ship, ship.GetName())
    mapped.RemoveObjectFromSet(tag + "a")
    plain.AddObjectToSet(a, tag + "a")
    b.SetRadius(4.5)
    c.SetScale(2.0)
    neb = App.MetaNebula_Create(0.1, 0.2, 0.3, 50.0, 0.4)
    neb.AddNebulaSphere(100, 200, 300, 40)
    neb.GetSeed()
    neb.AddNebulaSphere(-5, 6, -7, 8)
    mapped.AddObjectToSet(neb, tag + "neb")
    return {"mapped": mapped, "plain": plain, "a": a, "b": b, "c": c,
            "neb": neb}


def _normalised(world):
    world = dict(world)
    for n, o in list(world.items()):          # the ships' own subsystems
        for field in ("_sensor_subsystem", "_cloaking_subsystem", "_hull",
                      "_shield_subsystem", *_SYSTEM_FIELDS,
                      # unmirrored slots, named in mount_order
                      "_impulse_engine_subsystem", "_warp_engine_subsystem",
                      "_power_subsystem", "_repair_subsystem"):
            sub = o.__dict__.get(field)
            if sub is not None:
                world[n + field] = sub
    names = {_slot(o): n for n, o in world.items()}

    def norm(key, v):
        if key in _REF_FIELDS:
            if isinstance(v, list):
                return [names.get(x, x) for x in v]
            return names.get(v, v)
        if key == "profile":
            if v < 0:
                return v
            p = _h.combat_dump(v)
            return ([_hex(r) for r in p["rows"]],
                    float(p["full_concealment"]).hex())
        if isinstance(v, float):
            return v.hex()
        if isinstance(v, tuple):
            return _hex(v)
        if isinstance(v, list):
            return [_hex(x) if isinstance(x, tuple) else x for x in v]
        return v

    return {n: {k: norm(k, v) for k, v in _dump(o).items()
                if k not in _PER_PROCESS}
            for n, o in world.items()}


def test_resync_matches_incremental():
    from engine.appc import sensor_dials
    assert not nc.enabled()
    off_world = _build_world("off")
    sensor_dials._step("cloak_bubble_cap_gu", +1)     # a dial moved while off
    nc.configure(ON)                                  # resync
    assert _dump(off_world["a"])["_containing_set"] == _slot(
        off_world["plain"])
    on_world = _build_world("on")
    assert _normalised(off_world) == _normalised(on_world)
    _assert_globals_match_python()
    nc.audit_mirror()
    assert nc.audit_failures() == []


def test_audit_flags_a_bypassed_set_write():
    nc.configure(ON)
    pSet = _set("world_audit")
    ship = App.ShipClass_Create("Bypassed")
    contact_index._buckets.setdefault(pSet, []).append(ship)  # no push
    nc.audit_mirror()
    assert ("SetClass", "ships") in nc.audit_failures()
