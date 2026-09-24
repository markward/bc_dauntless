"""Per-frame eligibility: player always included; remaining slots filled by a
proximity+size score; capped at max_count. Deterministic for fixed inputs."""
import pytest

from engine.appc import damage_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


# All _Ship() instances default to this one shared, unmapped set, so distance
# scoring in the existing tests below (none of which care about frames) stays
# byte-identical to a raw Euclidean distance: same set -> offset (0, 0, 0).
_DEFAULT_SET = None


def _default_set():
    global _DEFAULT_SET
    if _DEFAULT_SET is None:
        from engine.appc.sets import SetClass_Create
        _DEFAULT_SET = SetClass_Create()
    return _DEFAULT_SET


class _Ship:
    def __init__(self, pos=(0.0, 0.0, 0.0), radius=1.0, pSet=None):
        self._pos = pos
        self._radius = radius
        self._set = pSet if pSet is not None else _default_set()

    def GetWorldLocation(self):
        return _Pt(*self._pos)

    def GetRadius(self):
        return self._radius

    def GetContainingSet(self):
        return self._set


@pytest.fixture(autouse=True)
def _clean():
    de.reset()
    yield
    de.reset()


def test_player_always_eligible_even_if_far_and_small():
    player = _Ship(pos=(1000.0, 0.0, 0.0), radius=0.1)
    near_big = _Ship(pos=(1.0, 0.0, 0.0), radius=50.0)
    ids = de.select_eligible(player, [player, near_big], max_count=1)
    assert id(player) in ids
    assert id(near_big) not in ids


def test_cap_respected():
    player = _Ship()
    others = [_Ship(pos=(float(i), 0.0, 0.0), radius=1.0) for i in range(1, 10)]
    ids = de.select_eligible(player, [player] + others, max_count=4)
    assert len(ids) == 4
    assert id(player) in ids


def test_nearest_preferred_for_equal_size():
    player = _Ship(pos=(0.0, 0.0, 0.0))
    near = _Ship(pos=(2.0, 0.0, 0.0), radius=1.0)
    far = _Ship(pos=(500.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(player, [player, near, far], max_count=2)
    assert id(near) in ids
    assert id(far) not in ids


def test_largest_preferred_for_equal_distance():
    player = _Ship(pos=(0.0, 0.0, 0.0))
    big = _Ship(pos=(10.0, 0.0, 0.0), radius=80.0)
    small = _Ship(pos=(10.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(player, [player, big, small], max_count=2)
    assert id(big) in ids
    assert id(small) not in ids


def test_select_without_player_uses_size_only():
    big = _Ship(pos=(999.0, 0.0, 0.0), radius=50.0)
    small = _Ship(pos=(0.0, 0.0, 0.0), radius=1.0)
    ids = de.select_eligible(None, [big, small], max_count=1)
    assert id(big) in ids
    assert id(small) not in ids


def test_is_eligible_reads_current_set():
    s = _Ship()
    assert de.is_eligible(s) is False
    de.set_current(frozenset({id(s)}))
    assert de.is_eligible(s) is True
    de.reset()
    assert de.is_eligible(s) is False


def test_player_always_wins_over_zero_cap():
    # Degenerate max_count=0: player-always (spec §4) overrides the cap.
    player = _Ship()
    other = _Ship(pos=(1.0, 0.0, 0.0))
    ids = de.select_eligible(player, [player, other], max_count=0)
    assert ids == frozenset({id(player)})


def test_all_zero_radii_no_divide_by_zero():
    player = _Ship(radius=0.0)
    other = _Ship(pos=(1.0, 0.0, 0.0), radius=0.0)
    ids = de.select_eligible(player, [player, other], max_count=2)
    assert id(player) in ids and id(other) in ids


def test_empty_ship_list_returns_player_only():
    player = _Ship()
    assert de.select_eligible(player, [], max_count=4) == frozenset({id(player)})


def test_update_falls_back_when_no_game(monkeypatch):
    # update() must be exception/absence safe: no App.Game_GetCurrentGame ->
    # player=None -> size-only selection, no raise.
    import App
    monkeypatch.delattr(App, "Game_GetCurrentGame", raising=False)
    big = _Ship(pos=(0.0, 0.0, 0.0), radius=50.0)
    small = _Ship(pos=(1.0, 0.0, 0.0), radius=1.0)
    de.update([big, small])
    assert id(big) in de.current()


def test_update_resolves_player_and_refreshes(monkeypatch):
    player = _Ship(pos=(0.0, 0.0, 0.0), radius=1.0)
    other = _Ship(pos=(1.0, 0.0, 0.0), radius=1.0)

    class _Game:
        def GetPlayer(self):
            return player

    import App
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)
    de.update([player, other])
    assert de.is_eligible(player) is True
    assert id(other) in de.current()


# ── frame-aware proximity (system-frames spec §1) ───────────────────────────
# Two regions of one star system share a frame; an unrelated plain set (e.g.
# QuickBattle) does not. A ship in another frame must score on size alone --
# no proximity credit, however close its raw local numbers look.

def test_a_ship_in_another_frame_gets_no_proximity_credit():
    import App
    from engine.appc.sets import SetClass_Create
    from tests.helpers.mapped_regions import load_region

    ona1 = load_region("Ona", "Ona1")
    qb = SetClass_Create()
    App.g_kSetManager.AddSet(qb, "QuickBattle")
    try:
        player = _Ship(pos=(0.0, 0.0, 0.0), pSet=ona1)
        # Equal size (radius=10 on both), so the contest is decided purely by
        # the proximity term. near_other's RAW local numbers put it far
        # closer to the player than near_same -- a raw (frame-blind) distance
        # compare would wrongly prefer it. Frame-aware scoring must instead
        # give it ZERO proximity credit (different frame from the player) and
        # pick near_same, the one actually near in the player's own frame.
        far_in_frame = _Ship(pos=(100.0, 0.0, 0.0), radius=10.0, pSet=ona1)
        near_raw_only = _Ship(pos=(1.0, 0.0, 0.0), radius=10.0, pSet=qb)
        # Player-always claims one slot (spec §4); max_count=2 leaves exactly
        # one contested slot.
        ids = de.select_eligible(player, [near_raw_only, far_in_frame], max_count=2)
        assert ids == frozenset({id(player), id(far_in_frame)})
    finally:
        # load_region() and AddSet() above register into the shared set
        # manager; this test owns cleaning that up (see
        # tests/conftest.py:_reset_leakable_engine_globals, which deliberately
        # leaves g_kSetManager._sets alone for module-scoped fixtures).
        App.g_kSetManager._sets.clear()
