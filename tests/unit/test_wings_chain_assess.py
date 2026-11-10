from engine.wings import chain, assess
from engine.wings.assess import ShipView

MEMBERS = [("a", 500), ("b", 1000), ("c", 1000), ("d", 200), ("e", 100),
           ("f", 50), ("g", 40), ("h", 30), ("i", 20), ("j", 10)]


def test_chain_size_table():
    assert [chain.chain_size(n) for n in (1, 4, 5, 9, 10, 25)] == [1, 1, 1, 1, 2, 5]


def test_build_chain_power_order_and_ties():
    assert chain.build_chain(MEMBERS, None) == ["b", "c"]


def test_build_chain_player_first():
    assert chain.build_chain(MEMBERS, "P") == ["P", "b"]


def test_current_commander_skips_dead():
    alive = {"b": True, "c": False, "d": True}
    assert chain.current_commander(["c", "b", "d"], lambda n: alive[n]) == "b"
    assert chain.current_commander(["c"], lambda n: False) is None
    assert chain.current_commander([], lambda n: True) is None


def _v(name, pos=(0.0, 0.0, 0.0), hull=1.0, shield=1.0, power=1000.0):
    return ShipView(name, pos, hull, shield, power)


def test_strength_formula():
    assert assess.strength(_v("x", hull=0.5, shield=0.0)) == 250.0
    assert assess.strength(_v("x", hull=0.5, shield=1.0)) == 500.0


def test_weakest_ties_by_name():
    assert assess.weakest([_v("b"), _v("a"), _v("c", hull=0.9)]).name == "c"
    assert assess.weakest([_v("b"), _v("a")]).name == "a"
    assert assess.weakest([]) is None


def test_dist_and_side_strength():
    assert assess.dist((0, 0, 0), (3, 4, 0)) == 5.0
    views = [_v("a", pos=(10, 0, 0)), _v("b", pos=(500, 0, 0))]
    assert assess.side_strength(views, (0, 0, 0), 100.0) == 1000.0


def test_fraction_beyond():
    views = [_v("a", pos=(10, 0, 0)), _v("b", pos=(500, 0, 0))]
    assert assess.fraction_beyond(views, (0, 0, 0), 100.0) == 0.5
    assert assess.fraction_beyond([], (0, 0, 0), 100.0) == 0.0
