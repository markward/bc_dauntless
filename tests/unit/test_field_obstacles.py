from engine.rocks import field_obstacles, promotion


class R:
    def __init__(self, hits, enabled=True):
        self.hits, self.enabled, self.calls = hits, enabled, []
    def far_enabled(self):
        return self.enabled
    def rockfield_query_large(self, c, radius, min_r):
        self.calls.append((c, radius, min_r))
        return self.hits


def test_returns_view_space_spheres_minus_promoted(monkeypatch):
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: ("Sys", (1000.0, 0.0, 0.0)))
    monkeypatch.setattr(promotion, "promoted", lambda: {9: object()})
    r = R([{"key": 1, "pos": (1100.0, 5.0, 0.0), "radius": 2.0},
           {"key": 9, "pos": (1050.0, 0.0, 0.0), "radius": 4.5}])
    out = field_obstacles.near(vs, (90.0, 0.0, 0.0), 150.0, r=r)
    assert out == [(100.0, 5.0, 0.0, 2.0)]
    assert r.calls[0][0] == (1090.0, 0.0, 0.0)          # system = anchor + view


def test_empty_when_not_the_viewed_set_or_disabled(monkeypatch):    # Review Focus 5
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: object())
    assert field_obstacles.near(object(), (0.0, 0.0, 0.0), 150.0, r=R([])) == []
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: ("Sys", (0.0, 0.0, 0.0)))
    assert field_obstacles.near(vs, (0.0, 0.0, 0.0), 150.0, r=R([], enabled=False)) == []


def test_never_raises(monkeypatch):
    vs = object()
    monkeypatch.setattr("engine.systems.frames.viewing_set", lambda: vs)
    monkeypatch.setattr("engine.rocks.far_tier.frame_for", lambda s: 1 / 0)
    assert field_obstacles.near(vs, (0.0, 0.0, 0.0), 150.0, r=R([])) == []
