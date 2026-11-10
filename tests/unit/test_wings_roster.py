import App
from engine.appc.objects import ObjectGroup
from engine.wings import roster


def setup_function(_):
    roster.reset()


def test_create_lookup_reset():
    w = roster.create_wing("w1", ObjectGroup())
    m = roster.add_member(w, "A")
    assert roster.wing_of("A") is w
    assert roster.member("A") is m
    assert roster.wings() == [w]
    roster.reset()
    assert roster.wing_of("A") is None
    assert roster.member("A") is None
    assert roster.wings() == []


def test_duplicate_add_idempotent():
    w = roster.create_wing("w1", ObjectGroup())
    m1 = roster.add_member(w, "A")
    m2 = roster.add_member(w, "A")
    assert m1 is m2
    assert list(w.members) == ["A"]


def test_member_defaults_not_shared():
    w = roster.create_wing("w1", ObjectGroup())
    a = roster.add_member(w, "A", chain_eligible=False)
    b = roster.add_member(w, "B", is_player=True)
    assert a.in_chain_eligible is False and b.is_player
    a.conditions["x"] = 1
    a.select_nodes.append(1)
    assert b.conditions == {} and b.select_nodes == []
    assert a.ram_script is None and a.desperate is None and a.rejoin is False


def test_target_group_seeded_from_enemy_group():
    g = ObjectGroup()
    g.AddName("E1")
    g.AddName("E2")
    w = roster.create_wing("w1", g)
    assert set(w.target_group.GetNameTuple()) == {"E1", "E2"}
    assert w.target_group["E1"] == {"Priority": 0.0}
    assert w.target_group["E2"] == {"Priority": 0.0}


def test_rng_deterministic_per_wing_id():
    a = roster.create_wing("alpha", ObjectGroup())
    seq = [a.rng.random() for _ in range(3)]
    roster.reset()
    a2 = roster.create_wing("alpha", ObjectGroup())
    assert [a2.rng.random() for _ in range(3)] == seq
    b = roster.create_wing("beta", ObjectGroup())
    assert [b.rng.random() for _ in range(3)] != seq


def test_defaults():
    w = roster.create_wing("w", ObjectGroup())
    assert w.chain == [] and w.commander is None and not w.leaderless
    assert w.km_priorities() == {}
    assert w.phase_s == 0.0 and w.accum_s == 0.0
