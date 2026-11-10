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


def test_dist_is_bit_identical_to_the_zip_sum():
    """dist's 3-vector fast path sums the same squares in the same order as
    the general zip form (sum() of floats, whichever Python), so every
    reach / leash comparison is unchanged; other lengths keep zip's
    truncation."""
    import math
    import random

    def ref(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    rng = random.Random(7)
    for _ in range(2000):
        a = tuple(rng.uniform(-1e4, 1e4) for _ in range(3))
        b = tuple(rng.uniform(-1e4, 1e4) for _ in range(3))
        assert assess.dist(a, b) == ref(a, b)
    assert assess.dist([1, 2, 3], (4.5, 6, 8)) == ref([1, 2, 3], (4.5, 6, 8))
    assert assess.dist((0, 0), (3, 4, 12)) == 5.0
    assert assess.dist((1, 2, 3, 9), (1, 2, 3)) == 0.0


def test_fraction_beyond():
    views = [_v("a", pos=(10, 0, 0)), _v("b", pos=(500, 0, 0))]
    assert assess.fraction_beyond(views, (0, 0, 0), 100.0) == 0.5
    assert assess.fraction_beyond([], (0, 0, 0), 100.0) == 0.0
