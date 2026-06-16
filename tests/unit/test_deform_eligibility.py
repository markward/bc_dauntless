"""Per-frame eligibility: player always included; remaining slots filled by a
proximity+size score; capped at max_count. Deterministic for fixed inputs."""
import pytest

from engine.appc import deform_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Ship:
    def __init__(self, pos=(0.0, 0.0, 0.0), radius=1.0):
        self._pos = pos
        self._radius = radius

    def GetWorldLocation(self):
        return _Pt(*self._pos)

    def GetRadius(self):
        return self._radius


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
